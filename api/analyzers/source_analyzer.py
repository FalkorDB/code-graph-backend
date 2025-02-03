from contextlib import nullcontext
from pathlib import Path
from typing import Optional

from api.entities.cls import Class
from api.entities.entity import Entity
from api.entities.file import File
from api.entities.function import Function

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
analyzers: dict[str, AbstractAnalyzer] = {
    # '.c': CAnalyzer(),
    # '.h': CAnalyzer(),
    '.py': PythonAnalyzer(),
    '.java': JavaAnalyzer()}

class NullLanguageServer:
    def start_server(self):
        return nullcontext()

class SourceAnalyzer():
    def __init__(self) -> None:
        self.files: dict[Path, File] = {}

    def supported_types(self) -> list[str]:
        """
        """
        return list(analyzers.keys())
    
    def create_hierarchy(self, analyzer: AbstractAnalyzer, file: File):
        types = analyzer.get_top_level_entity_types()
        stack = [file.tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in types:
                entity = Entity(node)
                analyzer.add_symbols(entity)
                analyzer.add_children(entity)
                file.add_entity(entity)
            else:
                stack.extend(node.children)

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

            # Skip ignored files
            if any([i in str(file_path) for i in ignore]):
                logging.info(f"Skipping ignored file {file_path}")
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
            for node, entity in file.entities.items():
                cls = Class(str(file_path), analyzer.get_entity_name(node), analyzer.get_entity_docstring(node), node.start_point.row, node.end_point.row)
                graph.add_class(cls)
                entity.id = cls.id
                graph.connect_entities("DEFINES", file.id, cls.id)
                for node, entity in entity.children.items():
                    fn = Function(str(file_path), analyzer.get_entity_name(node), analyzer.get_entity_docstring(node), None, node.text.decode("utf-8"), node.start_point.row, node.end_point.row)
                    graph.add_function(fn)
                    entity.id = fn.id
                    graph.connect_entities("DEFINES", cls.id, fn.id)

    def second_pass(self, graph: Graph, path: Path) -> None:
        """
        Recursively analyze the contents of a directory.

        Args:
            base (str): The base directory for analysis.
            root (str): The current directory being analyzed.
            executor (concurrent.futures.Executor): The executor to run tasks concurrently.
        """

        logger = MultilspyLogger()
        logger.logger.setLevel(logging.ERROR)
        lsps = {}
        if any(path.rglob('*.java')):
            config = MultilspyConfig.from_dict({"code_language": "java"})
            lsps[".java"] = SyncLanguageServer.create(config, logger, str(path))
        else:
            lsps[".java"] = NullLanguageServer()
        if any(path.rglob('*.py')):
            config = MultilspyConfig.from_dict({"code_language": "python"})
            lsps[".py"] = SyncLanguageServer.create(config, logger, str(path))
        else:
            lsps[".py"] = NullLanguageServer()
        with lsps[".java"].start_server(), lsps[".py"].start_server():
            for file_path, file in self.files.items():
                logging.info(f'Processing file: {file_path}')
                for _, entity in file.entities.items():
                    entity.resolved_symbol(lambda key, symbol: analyzers[file_path.suffix].resolve_symbol(self.files, lsps[file_path.suffix], file_path, key, symbol))
                    for key, symbols in entity.resolved_symbols.items():
                        for symbol in symbols:
                            if key == "base_class":
                                graph.connect_entities("EXTENDS", entity.id, symbol.id)
                            elif key == "implement_interface":
                                graph.connect_entities("IMPLEMENTS", entity.id, symbol.id)
                            elif key == "extend_interface":
                                graph.connect_entities("EXTENDS", entity.id, symbol.id)
                    for _, child in entity.children.items():
                        child.resolved_symbol(lambda key, symbol: analyzers[file_path.suffix].resolve_symbol(self.files, lsps[file_path.suffix], file_path, key, symbol))
                        for key, symbols in child.resolved_symbols.items():
                            for symbol in symbols:
                                if key == "call":
                                    graph.connect_entities("CALLS", child.id, symbol.id)
                                elif key == "return_type":
                                    graph.connect_entities("RETURNS", child.id, symbol.id)
                                elif key == "parameters":
                                    graph.connect_entities("PARAMETERS", child.id, symbol.id)

    def analyze_file(self, file_path: Path, path: Path, graph: Graph) -> None:
        ext = file_path.suffix
        logging.info(f"analyze_file: path: {file_path}")
        logging.info(f"analyze_file: ext: {ext}")
        if ext not in analyzers:
            return

        self.first_pass(file_path, [], graph)
        self.second_pass(graph, path)

    def analyze_sources(self, path: Path, ignore: list[str], graph: Graph) -> None:
        # First pass analysis of the source code
        self.first_pass(path, ignore, graph)

        # Second pass analysis of the source code
        self.second_pass(graph, path)

    def analyze_local_folder(self, path: str, g: Graph, ignore: Optional[list[str]] = []) -> None:
        """
        Analyze path.

        Args:
            path (str): Path to a local folder containing source files to process
            ignore (List(str)): List of paths to skip
        """

        logging.info(f"Analyzing local folder {path}")

        # Analyze source files
        self.analyze_sources(Path(path), ignore, g)

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
    
