from more_itertools import first
import tqdm
from pathlib import Path
from typing import Callable, Optional, Self
import tree_sitter_java
from tree_sitter import Language, Parser, Node, Point, Tree
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from falkordb import FalkorDB

# PATH = "/Users/aviavni/repos/jedis"
PATH = "/Users/aviavni/repos/JFalkorDB"
config = MultilspyConfig.from_dict({"code_language": "java"})
logger = MultilspyLogger()
lsp = SyncLanguageServer.create(config, logger, PATH)

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

class Entity:
    def __init__(self, node: Node):
        self.node = node
        self.symbols: dict[str, list[Node]] = {}
        self.resolved_symbols: dict[str, set[Self]] = {}
        self.children: dict[Node, Self] = {}

    def add_symbol(self, key: str, symbol: Node):
        if symbol is None:
            raise ValueError(f"Symbol is None for key {key}")
        if key not in self.symbols:
            self.symbols[key] = []
        self.symbols[key].append(symbol)

    def add_resolved_symbol(self, key: str, symbol: Self):
        if key not in self.resolved_symbols:
            self.resolved_symbols[key] = set()
        self.resolved_symbols[key].add(symbol)

    def add_child(self, child: Self):
        child.parent = self
        self.children[child.node] = child

    def resolved_symbol(self, f: Callable[[str, Node], list[Self]]):
        for _, child in self.children.items():
            child.resolved_symbol(f)

        for key, symbols in self.symbols.items():
            resolved_symbols = set()
            for symbol in symbols:
                for resolved_symbol in f(key, symbol):
                    resolved_symbols.add(resolved_symbol)
            if len(resolved_symbols) > 0:
                self.resolved_symbols[key] = resolved_symbols

class File:
    def __init__(self, path: Path, tree: Tree):
        self.path = path
        self.tree = tree
        self.types: dict[Node, Entity] = {}

    def add_type(self, type: Entity):
        self.parent = self
        self.types[type.node] = type

def find_parent(node: Node, parent_types: list) -> Node:
    while node.type not in parent_types:
        node = node.parent
    return node

def find_calls(method: Entity):
    query = JAVA_LANGUAGE.query("(method_invocation) @reference.call")
    captures = query.captures(method.node)
    if 'reference.call' in captures:
        for caller in captures['reference.call']:
            method.add_symbol("call", caller)

def find_methods(type: Entity):
    query = JAVA_LANGUAGE.query("[(method_declaration) (constructor_declaration)] @definition.method")
    captures = query.captures(type.node)
    if 'definition.method' in captures:
        for method_dec in captures['definition.method']:
            method = Entity(method_dec)
            query = JAVA_LANGUAGE.query("(formal_parameters (formal_parameter type: (_) @parameter))")
            captures = query.captures(method_dec)
            if 'parameter' in captures:
                for parameter in captures['parameter']:
                    method.add_symbol("parameters", parameter)
            if method_dec.type == 'method_declaration':
                method.add_symbol("return_type", method_dec.child_by_field_name('type'))
            type.add_child(method)
            find_calls(method)

def find_type(file: File):
    query = JAVA_LANGUAGE.query("[(class_declaration) (interface_declaration) (enum_declaration)] @type")
    captures = query.captures(file.tree.root_node)
    if 'type' in captures:
        for type_dec in captures['type']:
            if type_dec.type == 'class_declaration':
                type = Entity(type_dec)
                interfaces_query = JAVA_LANGUAGE.query("(super_interfaces (type_list (type_identifier) @interface))")
                interfaces_captures = interfaces_query.captures(type_dec)
                if 'interface' in interfaces_captures:
                    for interface in interfaces_captures['interface']:
                        type.add_symbol("implement_interface", interface)
                base_class_query = JAVA_LANGUAGE.query("(superclass (type_identifier) @base_class)")
                base_class_captures = base_class_query.captures(type_dec)
                if 'base_class' in base_class_captures:
                    base_class = base_class_captures['base_class'][0]
                    type.add_symbol("base_class", base_class)
            elif type_dec.type == 'interface_declaration':
                type = Entity(type_dec)
                query = JAVA_LANGUAGE.query("(extends_interfaces (type_list (type_identifier) @type))?")
                extends_captures = query.captures(type_dec)
                if 'type' in extends_captures:
                    for interface in extends_captures['type']:
                        type.add_symbol("extend_interface", interface)
            elif type_dec.type == 'enum_declaration':
                type = Entity(type_dec)
            file.add_type(type)
            find_methods(type)

def resolve(lsp: SyncLanguageServer, path: Path, node: Node) -> list[tuple[File, Node]]:
    return [(files[Path(location['absolutePath'])], files[Path(location['absolutePath'])].tree.root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))) for location in lsp.request_definition(str(path), node.start_point.row, node.start_point.column) if Path(location['absolutePath']) in files]

def resolve_type(lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
    res = []
    for file, resolved_node in resolve(lsp, path, node):
        type_dec = find_parent(resolved_node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
        res.append(file.types[type_dec])
    return res

def resolve_method(lsp: SyncLanguageServer, path: Path, node: Node) -> list[Entity]:
    res = []
    for file, resolved_node in resolve(lsp, path, node):
        method_dec = find_parent(resolved_node, ['method_declaration', 'constructor_declaration', 'class_declaration', 'interface_declaration', 'enum_declaration'])
        if method_dec.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
            continue
        type_dec = find_parent(method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
        res.append(file.types[type_dec].children[method_dec])
    return res

files: dict[Path, File] = {}

for path in tqdm.tqdm(Path(PATH).rglob("*.java"), "Parse files"):
    if 'test' in str(path):
        continue

    # Parse file
    source_code = path.read_bytes()
    tree = parser.parse(source_code)
    file = File(path, tree)
    files[path] = file

    find_type(file)

def resolve_symbol(key: str, symbol: Node) -> Entity:
    if key in ["implement_interface", "base_class", "extend_interface", "parameters", "return_type"]:
        return resolve_type(lsp, path, symbol)
    elif key in ["call"]:
        return resolve_method(lsp, path, symbol)
    else:
        raise ValueError(f"Unknown key {key}")

with lsp.start_server():
    for path, file in tqdm.tqdm(files.items(), "Resolve file"):
        for type_dec, type in file.types.items():
            if type.node.type == 'class_declaration':
                type.resolved_symbol(resolve_symbol)

graph = FalkorDB().select_graph("java")

try:
    graph.delete()
except:
    pass

graph.create_node_range_index("File", "path")
graph.create_node_range_index("Type", "name")
graph.create_node_range_index("Method", "name", "parameters")

nodes_created = 0
relationships_created = 0
for path, file in tqdm.tqdm(files.items(), "Save file hierarchy"):
    params = {"path": str(path)}
    query = "CREATE (file:File {path: $path})\n"
    for i, (class_dec, class_obj) in enumerate(file.types.items()):
        params[f"type_name_{i}"] = class_dec.child_by_field_name('name').text.decode('utf-8')
        query += f"CREATE (file)-[:DECLARE]->(type_{i}:Type {{name: $type_name_{i}}})\n"
        for j, (_, method_obj) in enumerate(class_obj.children.items()):
            params[f"method_name_{i}_{j}"] = method_obj.node.child_by_field_name('name').text.decode('utf-8')
            params[f"mathod_params_{i}_{j}"] = method_obj.node.child_by_field_name('parameters').text.decode('utf-8')
            query += f"CREATE (type_{i})-[:HAS_METHOD]->(method_{i}_{j}:Method {{name: $method_name_{i}_{j}, parameters: $mathod_params_{i}_{j}}})\n"
    res = graph.query(query, params)
    nodes_created += res.nodes_created
    relationships_created += res.relationships_created
print(f"Created {nodes_created} nodes and {relationships_created} relationships")

for path, file in tqdm.tqdm(files.items(), "Save calls"):
    for class_dec, class_obj in file.types.items():
        if "implement_interface" in class_obj.resolved_symbols:
            for interface in class_obj.resolved_symbols["implement_interface"]:
                query = "MATCH (file:File {path: $path})\n"
                params = {"path": str(path)}
                query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
                params["type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
                query += f"MATCH (interface:Type {{name: $interface_name}})\n"
                params["interface_name"] = interface.node.child_by_field_name('name').text.decode('utf-8')
                query += f"MERGE (type)-[:IMPLEMENTS]->(interface)\n"
                query += "RETURN *"
                res = graph.query(query, params)
        if "base_class" in class_obj.resolved_symbols:
            query = "MATCH (file:File {path: $path})\n"
            params = {"path": str(path)}
            query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
            params["type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
            query += f"MATCH (base_class:Type {{name: $base_class_name}})\n"
            params["base_class_name"] = first(class_obj.resolved_symbols["base_class"]).node.child_by_field_name('name').text.decode('utf-8')
            query += f"MERGE (type)-[:EXTENDS]->(base_class)\n"
            query += "RETURN *"
            res = graph.query(query, params)
        for _, method_obj in class_obj.children.items():
            params = {}
            query = "MATCH (file:File {path: $path})\n"
            params["path"] = str(path)
            query += f"MATCH (file)-[:DECLARE]->(type:Type {{name: $type_name}})\n"
            params[f"type_name"] = class_dec.child_by_field_name('name').text.decode('utf-8')
            query += f"MATCH (type)-[:HAS_METHOD]->(caller:Method {{name: $method_name, parameters: $mathod_params}})\n"
            params[f"method_name"] = method_obj.node.child_by_field_name('name').text.decode('utf-8')
            params[f"mathod_params"] = method_obj.node.child_by_field_name('parameters').text.decode('utf-8')
            if "call" in method_obj.resolved_symbols:
                for i, call in enumerate(method_obj.resolved_symbols["call"]):
                    params[f"callee_class_name_{i}"] = call.parent.node.child_by_field_name('name').text.decode('utf-8')
                    params[f"callee_method_name_{i}"] = call.node.child_by_field_name('name').text.decode('utf-8')
                    params[f"callee_mathod_params_{i}"] = call.node.child_by_field_name('parameters').text.decode('utf-8')
                    query += f"MATCH (:Type {{name: $callee_class_name_{i}}})-[:HAS_METHOD]->(callee_{i}:Method {{name: $callee_method_name_{i}, parameters: $callee_mathod_params_{i}}})\n"
                    query += f"MERGE (caller)-[:CALLS]->(callee_{i})\n"
                    query += f"WITH file, type, caller\n"
            query += "RETURN *"
            res = graph.query(query, params)
