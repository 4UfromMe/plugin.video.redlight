# -*- coding: utf-8 -*-
from threading import Thread, Lock
from apis.premiumize_api import Premiumize
from modules import source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

class source:
	def __init__(self):
		self.scrape_provider = 'pm_cloud'
		self.sources = []
		self.Premiumize = Premiumize()
		self.extensions = source_utils.supported_video_extensions()
		# Track matched Premiumize folder paths so files from those folders can bypass per-file title checks.
		self._matched_folder_paths = set()
		self._matched_lock = Lock()

	def results(self, info):
		try:
			if not enabled_debrids_check('pm'): return source_utils.internal_results(self.scrape_provider, self.sources)
			self.folder_results, self.scrape_results = [], []
			self.filter_title = filter_by_name(self.scrape_provider)
			self.media_type, title = info.get('media_type'), info.get('title')
			self.year, self.season, self.episode = int(info.get('year') or 0), info.get('season'), info.get('episode')
			self.absolute_episode = info.get('absolute_episode')
			self.title = title
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self.folder_query = source_utils.clean_title(normalize(title))
			self.folder_queries = source_utils.folder_title_queries(title, self.aliases)
			self._scrape_cloud()
			if not self.scrape_results: return source_utils.internal_results(self.scrape_provider, self.sources)
			def _process():
				for item in self.scrape_results:
					try:
						file_name = normalize(item['path'])
						# allow bypass when file was inside a matched folder
						file_from_matched_folder = bool(item.get('from_folder')) or (item.get('folder_path') and item.get('folder_path') in self._matched_folder_paths)
						if self.media_type == 'episode':
							if not source_utils.cloud_episode_matches(self.season, self.episode, file_name, self.absolute_episode): continue
							if self.filter_title and not file_from_matched_folder and not source_utils.check_title(title, file_name, self.aliases, self.year, 'pack', self.episode): continue
						elif self.filter_title and not file_from_matched_folder and not source_utils.check_title(title, file_name, self.aliases, self.year, self.season, self.episode): continue
						display_name = clean_file_name(file_name).replace('html', ' ').replace('+', ' ').replace('-', ' ')
						file_dl, size = item['link'], round(float(item.get('size', 0))/1073741824, 2)
						video_quality, details = source_utils.get_file_info(name_info=source_utils.release_info_format(file_name))
						source_item = {'name': file_name, 'display_name': display_name, 'quality': video_quality, 'size': size, 'size_label': '%.2f GB' % size,
									'extraInfo': details, 'url_dl': file_dl, 'id': file_dl, 'downloads': False, 'direct': True, 'source': self.scrape_provider,
									'debrid': self.scrape_provider, 'scrape_provider': self.scrape_provider, 'direct_debrid_link': True}
						yield source_item
					except Exception:
						pass
			self.sources = list(_process())
		except Exception as e:
			from modules.kodi_utils import logger
			logger('premiumize scraper Exception', str(e))
		source_utils.internal_results(self.scrape_provider, self.sources)
		return self.sources

	def _scrape_cloud(self):
		try:
			try:
				my_cloud_files = self.Premiumize.user_cloud()
			except Exception:
				return
			if not my_cloud_files: return
			results_append = self.folder_results.append
			for item in my_cloud_files:
				if item.get('type') != 'folder': continue
				folder_path = item.get('path', '')
				folder_name = item.get('name', '')
				normalized = normalize(folder_name)
				if not any(q and q in source_utils.clean_title(normalized) for q in self.folder_queries):
					# title/alias miss: only movies may fall through, and only on a year hit
					if self.media_type != 'movie': continue
					if not any(x in normalized for x in self._year_query_list()): continue
				if folder_path:
					results_append(folder_path)
					try:
						with self._matched_lock:
							self._matched_folder_paths.add(folder_path)
					except: pass
			if not self.folder_results: return
			threads = [Thread(target=self._scrape_folders, args=(i,)) for i in self.folder_results]
			[i.start() for i in threads]
			[i.join() for i in threads]
		except Exception:
			return

	def _scrape_folders(self, folder_path):
		try:
			if not folder_path: return
			folder_files = self.Premiumize.cloud_folder_contents(folder_path)
			if not folder_files: return
			scrape_results_append = self.scrape_results.append
			for item in folder_files:
				try:
					if item.get('type') != 'file': continue
					file_path = item.get('path', '')
					if not file_path.lower().endswith(tuple(self.extensions)): continue
					normalized = normalize(file_path)
					if self.media_type == 'episode' and not source_utils.cloud_episode_matches(self.season, self.episode, normalized, self.absolute_episode): continue
					# mark file as coming from a matched folder
					scrape_results_append({'path': file_path, 'link': item.get('link'), 'size': item.get('size', 0), 'from_folder': True, 'folder_path': folder_path})
				except Exception:
					continue
		except Exception:
			return

	def _year_query_list(self):
		return (str(self.year), str(self.year+1), str(self.year-1))

