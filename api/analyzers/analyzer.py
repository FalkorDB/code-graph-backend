from pathlib import Path
from typing import Optional

from tree_sitter import Language, Node, Parser, Point
from api.entities.entity import Entity
from api.entities.file import File
from abc import ABC, abstractmethod
from multilspy import SyncLanguageServer

class AbstractAnalyzer(ABC):
    def __init__(self, language: Language) -> None:
        self.language = language
        self.parser = Parser(language)

    def find_parent(self, node: Node, parent_types: list) -> Node:
        while node and node.type not in parent_types:
            node = node.parent
        return node

    def resolve(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[tuple[File, Node]]:
        try:
            return [(files[Path(location['absolutePath'])], files[Path(location['absolutePath'])].tree.root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))) for location in lsp.request_definition(str(path), node.start_point.row, node.start_point.column) if location and Path(location['absolutePath']) in files]
        except Exception as e:
            return []
    
    @abstractmethod
    def get_entity_label(self, node: Node) -> str:
        """
        Get the entity label from the node.

        Args:
            node (Node): The node.
        
        Returns:
            str: The entity label.
        """
        pass

    @abstractmethod
    def get_entity_name(self, node: Node) -> str:
        """
        Get the entity name from the node.

        Args:
            node (Node): The node.
        
        Returns:
            str: The entity name.
        """
        pass

    @abstractmethod
    def get_entity_docstring(self, node: Node) -> Optional[str]:
        """
        Get the entity docstring from the node.

        Args:
            node (Node): The node.

        Returns:
            Optional[str]: The entity docstring.
        """
        pass
    
    @abstractmethod
    def get_top_level_entity_types(self) -> list[str]:
        """
        Get the top level entity types for the language.

        Returns:
            list[str]: The list of top level entity types.
        """

        pass

    @abstractmethod
    def add_symbols(self, entity: Entity) -> None:
        """
        Add symbols to the entity.

        Args:
            entity (Entity): The entity to add symbols to.
        """

        pass

    @abstractmethod
    def add_children(self, entity: Entity) -> None:
        """
        Add children to the entity.

        Args:
            entity (Entity): The entity to add children to.
        """

        pass

    @abstractmethod
    def resolve_symbol(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, key: str, symbol: Node) -> Entity:
        """
        Resolve a symbol to an entity.

        Args:
            lsp (SyncLanguageServer): The language server.
            path (Path): The path to the file.
            key (str): The symbol key.
            symbol (Node): The symbol node.

        Returns:
            Entity: The entity.
        """

        pass

