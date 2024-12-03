import os
import shutil
import concurrent.futures

from pathlib import Path
from typing import Optional, List

from ..graph import Graph
from .c.analyzer import CAnalyzer
from .python.analyzer import PythonAnalyzer

import logging
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(filename)s - %(asctime)s - %(levelname)s - %(message)s')

# List of available analyzers
analyzers = {'.c': CAnalyzer(),
             '.h': CAnalyzer(),
             '.py': PythonAnalyzer()}

class SourceAnalyzer():

    def supported_types(self) -> List[str]:
        """
        """
        return list(analyzers.keys())

    def first_pass(self, ignore: List[str], executor: concurrent.futures.Executor) -> None:
        """
        Perform the first pass analysis on source files in the given directory tree.

        Args:
            ignore (list(str)): List of paths to ignore
            executor (concurrent.futures.Executor): The executor to run tasks concurrently.
        """

        tasks = []
        for dirpath, dirnames, filenames in os.walk("."):

            # skip current directory if it is within the ignore list
            if dirpath in ignore:
                # in-place clear dirnames to prevent os.walk from recursing into
                # any of the nested directories
                logging.info(f'ignoring directory: {dirpath}')
                dirnames[:] = []
                continue

            logging.info(f'Processing directory: {dirpath}')

            # Process each file in the current directory
            for filename in filenames:
                file_path = Path(os.path.join(dirpath, filename))

                # Skip none supported files
                ext = file_path.suffix
                if ext not in analyzers:
                    logging.info(f"Skipping none supported file {file_path}")
                    continue

                logging.info(f'Processing file: {file_path}')

                def process_file(path: Path) -> None:
                    with open(path, 'rb') as f:
                        ext = path.suffix
                        analyzers[ext].first_pass(path, f, self.graph)

                process_file(file_path)
                #task = executor.submit(process_file, file_path)
                #tasks.append(task)

        # Wait for all tasks to complete
        #concurrent.futures.wait(tasks)

    def second_pass(self, ignore: List[str], executor: concurrent.futures.Executor) -> None:
        """
        Recursively analyze the contents of a directory.

        Args:
            base (str): The base directory for analysis.
            root (str): The current directory being analyzed.
            executor (concurrent.futures.Executor): The executor to run tasks concurrently.
        """

        tasks = []
        for dirpath, dirnames, filenames in os.walk("."):

            # skip current directory if it is within the ignore list
            if dirpath in ignore:
                # in-place clear dirnames to prevent os.walk from recursing into
                # any of the nested directories
                logging.info(f'ignoring directory: {dirpath}')
                dirnames[:] = []
                continue

            logging.info(f'Processing directory: {dirpath}')

            # Process each file in the current directory
            for filename in filenames:
                file_path = Path(os.path.join(dirpath, filename))

                # Skip none supported files
                ext = file_path.suffix
                if ext not in analyzers:
                    continue

                logging.info(f'Processing file: {file_path}')

                def process_file(path: Path) -> None:
                    with open(path, 'rb') as f:
                        ext = path.suffix
                        analyzers[ext].second_pass(path, f, self.graph)

                task = executor.submit(process_file, file_path)
                tasks.append(task)

        # Wait for all tasks to complete
        concurrent.futures.wait(tasks)

    def analyze_file(self, path: Path, graph: Graph) -> None:
        ext = path.suffix
        logging.info(f"analyze_file: path: {path}")
        logging.info(f"analyze_file: ext: {ext}")
        if ext not in analyzers:
            return

        with open(path, 'rb') as f:
            analyzers[ext].first_pass(path, f, graph)
            analyzers[ext].second_pass(path, f, graph)

    def analyze_sources(self, ignore: List[str]) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # First pass analysis of the source code
            self.first_pass(ignore, executor)

            # Second pass analysis of the source code
            self.second_pass(ignore, executor)

    def analyze_local_folder(self, path: str, g: Graph, ignore: Optional[List[str]] = []) -> None:
        """
        Analyze path.

        Args:
            path (str): Path to a local folder containing source files to process
            ignore (List(str)): List of paths to skip
        """

        logging.info(f"Analyzing local folder {path}")

        # Save original working directory for later restore
        original_dir = Path.cwd()

        # change working directory to path
        os.chdir(path)

        # Initialize the graph and analyzer
        self.graph = g

        # Analyze source files
        self.analyze_sources(ignore)

        logging.info("Done analyzing path")

        # Restore original working dir
        os.chdir(original_dir)

    def analyze_local_repository(self, path: str, ignore: Optional[List[str]] = []) -> Graph:
        """
        Analyze a local Git repository.

        Args:
            path (str): Path to a local git repository
            ignore (List(str)): List of paths to skip
        """
        from git import Repo

        self.analyze_local_folder(path, ignore)

        # Save processed commit hash to the DB
        repo = Repo(path)
        head = repo.commit("HEAD")
        self.graph.set_graph_commit(head.hexsha)

        return self.graph
    
