from pathlib import Path
from ...entities import *
from typing import Optional
from ..analyzer import AbstractAnalyzer

from multilspy import SyncLanguageServer

import tree_sitter_java as tsjava
from tree_sitter import Language, Node

import logging
logger = logging.getLogger('code_graph')

class JavaAnalyzer(AbstractAnalyzer):
    def __init__(self) -> None:
        super().__init__(Language(tsjava.language()))

    def get_entity_label(self, node: Node) -> str:
        if node.type == 'class_declaration':
            return "Class"
        elif node.type == 'interface_declaration':
            return "Interface"
        elif node.type == 'enum_declaration':
            return "Enum"
        elif node.type == 'method_declaration':
            return "Method"
        elif node.type == 'constructor_declaration':
            return "Constructor"
        raise ValueError(f"Unknown entity type: {node.type}")

    def get_entity_name(self, node: Node) -> str:
        if node.type in ['class_declaration', 'interface_declaration', 'enum_declaration', 'method_declaration', 'constructor_declaration']:
            return node.child_by_field_name('name').text.decode('utf-8')
        raise ValueError(f"Unknown entity type: {node.type}")
    
    def get_entity_docstring(self, node: Node) -> Optional[str]:
        if node.type in ['class_declaration', 'interface_declaration', 'enum_declaration', 'method_declaration', 'constructor_declaration']:
            if node.prev_sibling.type == "block_comment":
                return node.prev_sibling.text.decode('utf-8')
            return None
        raise ValueError(f"Unknown entity type: {node.type}")        

    def get_entity_types(self) -> list[str]:
        return ['class_declaration', 'interface_declaration', 'enum_declaration', 'method_declaration', 'constructor_declaration']
    
    def add_symbols(self, entity: Entity) -> None:
        if entity.node.type == 'class_declaration':
            interfaces_query = self.language.query("(super_interfaces (type_list (type_identifier) @interface))")
            interfaces_captures = interfaces_query.captures(entity.node)
            if 'interface' in interfaces_captures:
                for interface in interfaces_captures['interface']:
                    entity.add_symbol("implement_interface", interface)
            base_class_query = self.language.query("(superclass (type_identifier) @base_class)")
            base_class_captures = base_class_query.captures(entity.node)
            if 'base_class' in base_class_captures:
                base_class = base_class_captures['base_class'][0]
                entity.add_symbol("base_class", base_class)
        elif entity.node.type == 'interface_declaration':
            query = self.language.query("(extends_interfaces (type_list (type_identifier) @type))?")
            extends_captures = query.captures(entity.node)
            if 'type' in extends_captures:
                for interface in extends_captures['type']:
                    entity.add_symbol("extend_interface", interface)
        elif entity.node.type in ['method_declaration', 'constructor_declaration']:
            query = self.language.query("(method_invocation) @reference.call")
            captures = query.captures(entity.node)
            if 'reference.call' in captures:
                for caller in captures['reference.call']:
                    entity.add_symbol("call", caller)
            if entity.node.type == 'method_declaration':
                query = self.language.query("(formal_parameters (formal_parameter type: (_) @parameter))")
                captures = query.captures(entity.node)
                if 'parameter' in captures:
                    for parameter in captures['parameter']:
                        entity.add_symbol("parameters", parameter)
                entity.add_symbol("return_type", entity.node.child_by_field_name('type'))

    def resolve_type(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node):
            type_dec = self.find_parent(resolved_node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
            if type_dec in file.entities:
                res.append(file.entities[type_dec])
        return res

    def resolve_method(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node.child_by_field_name('name')):
            method_dec = self.find_parent(resolved_node, ['method_declaration', 'constructor_declaration', 'class_declaration', 'interface_declaration', 'enum_declaration'])
            if method_dec.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
                continue
            if method_dec in file.entities:
                res.append(file.entities[method_dec])
        return res
    
    def resolve_symbol(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, key: str, symbol: Node) -> Entity:
        if key in ["implement_interface", "base_class", "extend_interface", "parameters", "return_type"]:
            return self.resolve_type(files, lsp, path, symbol)
        elif key in ["call"]:
            return self.resolve_method(files, lsp, path, symbol)
        else:
            raise ValueError(f"Unknown key {key}")
