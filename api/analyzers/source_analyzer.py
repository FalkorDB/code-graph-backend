from pathlib import Path
from typing import Optional

from api.entities.entity import Entity
from api.entities.file import File

from ..graph import Graph
from .analyzer import AbstractAnalyzer
from .c.analyzer import CAnalyzer
from .java.analyzer import JavaAnalyzer
from .python.analyzer import PythonAnalyzer

from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

import logging
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(filename)s - %(asctime)s - %(levelname)s - %(message)s')

# List of available analyzers
analyzers: dict[str, AbstractAnalyzer] = {'.c': CAnalyzer(),
             '.h': CAnalyzer(),
             '.py': PythonAnalyzer(),
             '.java': JavaAnalyzer()}

class SourceAnalyzer():
    def __init__(self) -> None:
        self.files: dict[Path, File] = {}

    def supported_types(self) -> list[str]:
        """
        """
        return list(analyzers.keys())
    
    def create_hierarchy(self, analyzer: AbstractAnalyzer, file: File):
        types = analyzer.get_top_level_entity_types()
        query = analyzer.language.query(f"[{" ".join([f"({type})" for type in types])}] @top_level_entity")
        captures = query.captures(file.tree.root_node)
        if 'top_level_entity' in captures:
            for top_level_entity in captures['top_level_entity']:
                entity = Entity(top_level_entity)
                analyzer.add_symbols(entity)
                analyzer.add_children(entity)
                file.add_entity(entity)

    def first_pass(self, path: Path, ignore: list[str], graph: Graph) -> None:
        """
        Perform the first pass analysis on source files in the given directory tree.

        Args:
            ignore (list(str)): List of paths to ignore
            executor (concurrent.futures.Executor): The executor to run tasks concurrently.
        """

        for file_path in path.rglob('*.*'):
            # Skip none supported files
            if file_path.suffix not in analyzers:
                logging.info(f"Skipping none supported file {file_path}")
                continue

            logging.info(f'Processing file: {file_path}')

            analyzer = analyzers[file_path.suffix]

            # Parse file
            source_code = file_path.read_bytes()
            tree = analyzer.parser.parse(source_code)

            # Create file entity
            file = File(file_path, tree)
            self.files[file_path] = file

            # Walk thought the AST
            self.create_hierarchy(analyzer, file)

            graph.add_file(file)

    def second_pass(self, graph: Graph, lsp: SyncLanguageServer) -> None:
        """
        Recursively analyze the contents of a directory.

        Args:
            base (str): The base directory for analysis.
            root (str): The current directory being analyzed.
            executor (concurrent.futures.Executor): The executor to run tasks concurrently.
        """

        with lsp.start_server():
            for file_path, file in self.files.items():
                logging.info(f'Processing file: {file_path}')
                for _, entity in file.entities.items():
                    entity.resolved_symbol(lambda key, symbol: analyzers[file_path.suffix].resolve_symbol(self.lsp, file_path, key, symbol))

    def analyze_file(self, path: Path, lsp: SyncLanguageServer, graph: Graph) -> None:
        ext = path.suffix
        logging.info(f"analyze_file: path: {path}")
        logging.info(f"analyze_file: ext: {ext}")
        if ext not in analyzers:
            return

        self.first_pass(path, [], graph)
        self.second_pass(graph, lsp)

    def analyze_sources(self, path: Path, ignore: list[str], graph: Graph, lsp: SyncLanguageServer) -> None:
        # First pass analysis of the source code
        self.first_pass(path, ignore, graph)

        # Second pass analysis of the source code
        self.second_pass(graph, lsp)

    def analyze_local_folder(self, path: str, g: Graph, ignore: Optional[list[str]] = []) -> None:
        """
        Analyze path.

        Args:
            path (str): Path to a local folder containing source files to process
            ignore (List(str)): List of paths to skip
        """

        logging.info(f"Analyzing local folder {path}")

        config = MultilspyConfig.from_dict({"code_language": "java"})
        logger = MultilspyLogger()
        lsp = SyncLanguageServer.create(config, logger, path)

        # Analyze source files
        self.analyze_sources(path, ignore, g, lsp)

        logging.info("Done analyzing path")

    def analyze_local_repository(self, path: str, ignore: Optional[list[str]] = []) -> Graph:
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
    
