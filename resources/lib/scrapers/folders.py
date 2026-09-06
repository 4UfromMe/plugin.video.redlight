# -*- coding: utf-8 -*-
import os
import threading
from urllib.parse import urlparse
from caches.main_cache import cache_object
from modules import source_utils
from modules.kodi_utils import list_dirs, open_file
from modules.utils import clean_file_name, normalize, make_thread_list
from modules.settings import filter_by_name, max_threads
# from modules.kodi_utils import logger

class source:
	def __init__(self, scrape_provider, scraper_name, folder_path):
		self.scrape_provider = scrape_provider
		self.scraper_name = scraper_name
		self.folder_path = folder_path
		self.sources, self.scrape_results = [], []
		self.extensions = source_utils.supported_video_extensions()
		# Track folders that were matched by folder-name prefiltering.
		# Files inside these folders will bypass per-file title/alias filename checks.
		self._matched_folders = set()
		self._matched_folders_lock = threading.Lock()

	def results(self, info):
		try:
			if not self.folder_path: return source_utils.internal_results(self.scraper_name, self.sources)
			filter_title = filter_by_name('folders')
			self.media_type, title, self.year = info.get('media_type'), info.get('title'), int(info.get('year'))
			self.season, self.episode = info.get('season'), info.get('episode')
			self.tmdb_id = info.get('tmdb_id')
			self.title_query = source_utils.clean_title(normalize(title))
			self.folder_query = self._season_query_list() if self.media_type == 'episode' else self._year_query_list()
			self._scrape_directory(self.folder_path, first_run=True)
			if not self.scrape_results: return source_utils.internal_results(self.scraper_name, self.sources)
			aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			def _process():
				for item in self.scrape_results:
					try:
						file_name = normalize(item[0])
						# file_dl is the full path returned earlier by _scrape_directory
						file_dl = item[1]
						# determine whether file is inside a previously matched folder
						try:
							path_norm = os.path.normpath(file_dl)
							file_from_matched_folder = False
							with self._matched_folders_lock:
								for mf in self._matched_folders:
									if not mf: continue
									mf_norm = os.path.normpath(mf)
									if path_norm == mf_norm or path_norm.startswith(mf_norm + os.sep):
										file_from_matched_folder = True
										break
						except:
						file_from_matched_folder = False

						# If filter_title is enabled, require title in filename UNLESS the file
						# came from a folder previously matched by folder-name prefiltering.
						if filter_title and not (file_from_matched_folder or source_utils.check_title(title, file_name, aliases, self.year, self.season, self.episode)): continue
						display_name = clean_file_name(file_name).replace('html', ' ').replace('+', ' ').replace('-', ' ')
						try: size = item[2]
						except: size = self._get_size(file_dl)
						video_quality, details = source_utils.get_file_info(name_info=source_utils.release_info_format(file_name))
						source_item = {'name': file_name, 'display_name': display_name, 'quality': video_quality, 'size': size, 'size_label': '%.2f GB' % size, 'debrid': 'folders',
									'extraInfo': details, 'url_dl': file_dl, 'id': file_dl, self.scrape_provider : True, 'direct': True, 'source': self.scraper_name,
									'scrape_provider': 'folders'}
						yield source_item
					except: pass
			self.sources = list(_process())
		except Exception as e:
			from modules.kodi_utils import logger
			logger('RedLight folders scraper Exception', str(e))
		source_utils.internal_results(self.scraper_name, self.sources)
		return self.sources

	def _make_dirs(self, folder_name):
		folder_files = []
		folder_files_append = folder_files.append
		dirs, files =  list_dirs(folder_name)
		for i in dirs: folder_files_append((i, 'folder'))
		for i in files: folder_files_append((i, 'file'))
		return folder_files

	def _scrape_directory(self, folder_name, first_run=False):
		def _process(item):
			file_type = item[1]
			normalized = normalize(item[0])
			item_name = source_utils.clean_title(normalized)
			if file_type == 'file':
				ext = os.path.splitext(urlparse(item[0]).path)[-1].lower()
				if ext in self.extensions:
					if self.media_type == 'episode' and not source_utils.seas_ep_filter(self.season, self.episode, normalized): return
					url_path = self.url_path(folder_name, item[0])
					size = self._get_size(url_path)
					scrape_results_append((item[0], url_path, size))
			elif self.title_query in item_name or any(x in item_name for x in self.folder_query):
				# Matched folder — record it (thread-safe) so files inside can bypass checks.
				fpath = os.path.join(folder_name, item[0])
				folder_results_append((fpath))
				try:
					with self._matched_folders_lock:
						self._matched_folders.add(os.path.normpath(fpath))
				except:
					pass
		folder_results = []
		scrape_results_append = self.scrape_results.append
		folder_results_append = folder_results.append
		string = 'FOLDERSCRAPER_%s_%s' % (self.scrape_provider, folder_name)
		folder_files = cache_object(self._make_dirs, string, (folder_name), json=False, expiration=4)
		folder_threads = list(make_thread_list(_process, folder_files))
		[i.join() for i in folder_threads]
		if not folder_results: return
		return self._scraper_worker(folder_results)

	def _scraper_worker(self, folder_results):
		scraper_threads = list(make_thread_list(self._scrape_directory, folder_results))
		[i.join() for i in scraper_threads]

	def url_path(self, folder, file):
		return os.path.join(folder, file)

	def _get_size(self, file):
		if file.endswith('.strm'): return 'strm'
		with open_file(file) as f: s = f.size()
		return round(float(s)/1073741824, 2)

	def _year_query_list(self):
		return (str(self.year), str(self.year+1), str(self.year-1))

	def _season_query_list(self):
		return ('season%02d' % int(self.season), 'season%s' % self.season)
