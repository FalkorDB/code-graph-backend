from ..utils import *
from pathlib import Path
from ...entities import *
from ...graph import Graph
from typing import Optional
from ..analyzer import AbstractAnalyzer

from multilspy import SyncLanguageServer

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Point

import logging
logger = logging.getLogger('code_graph')

class JavaAnalyzer(AbstractAnalyzer):
    def __init__(self) -> None:
        super().__init__(Language(tsjava.language()))

    def get_entity_name(self, node: Node) -> str:
        if node.type in ['class_declaration', 'function_declaration']:
            return node.child_by_field_name('name').text.decode('utf-8')
        raise ValueError(f"Unknown entity type: {node.type}")
    
    def get_entity_docstring(self, node: Node) -> Optional[str]:
        if node.type == 'class_declaration':
            body = node.child_by_field_name('body')
            if body.child_count > 0 and body.children[0].type == 'expression_statement':
                docstring_node = body.children[0].child(0)
                return docstring_node.text.decode('utf-8')
        raise ValueError(f"Unknown entity type: {node.type}")
    
    def find_calls(self, method: Entity):
        query = self.language.query("(method_invocation) @reference.call")
        captures = query.captures(method.node)
        if 'reference.call' in captures:
            for caller in captures['reference.call']:
                method.add_symbol("call", caller)

    def find_methods(self, type: Entity):
        query = self.language.query("[(method_declaration) (constructor_declaration)] @definition.method")
        captures = query.captures(type.node)
        if 'definition.method' in captures:
            for method_dec in captures['definition.method']:
                method = Entity(method_dec)
                query = self.language.query("(formal_parameters (formal_parameter type: (_) @parameter))")
                captures = query.captures(method_dec)
                if 'parameter' in captures:
                    for parameter in captures['parameter']:
                        method.add_symbol("parameters", parameter)
                method.add_symbol("return_type", method_dec.child_by_field_name('type'))
                type.add_child(method)
                self.find_calls(method)

    def get_top_level_entity_types(self) -> list[str]:
        return ['class_declaration', 'interface_declaration', 'enum_declaration']
    
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

    def add_children(self, entity: Entity) -> None:
        self.find_methods(entity)

    def resolve_type(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node):
            type_dec = self.find_parent(resolved_node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
            res.append(file.entities[type_dec])
        return res

    def resolve_method(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
        res = []
        for file, resolved_node in self.resolve(files, lsp, path, node):
            method_dec = self.find_parent(resolved_node, ['method_declaration', 'constructor_declaration', 'class_declaration', 'interface_declaration', 'enum_declaration'])
            if method_dec.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
                continue
            type_dec = self.find_parent(method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
            res.append(file.entities[type_dec].children[method_dec])
        return res
    
    def resolve_symbol(self, files: dict[Path, File], lsp: SyncLanguageServer, path: Path, key: str, symbol: Node) -> Entity:
        if key in ["implement_interface", "base_class", "extend_interface", "parameters", "return_type"]:
            return self.resolve_type(files, lsp, path, symbol)
        elif key in ["call"]:
            return self.resolve_method(files, lsp, path, symbol)
        else:
            raise ValueError(f"Unknown key {key}")
