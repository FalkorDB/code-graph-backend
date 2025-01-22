from pathlib import Path
from typing import Self
import tree_sitter_java
from tree_sitter import Language, Parser, Node, Point
from multilspy import SyncLanguageServer
from multilspy.multilspy_types import SymbolKind
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from falkordb import FalkorDB

config = MultilspyConfig.from_dict({"code_language": "java", "trace_lsp_communication": True}) # Also supports "python", "rust", "csharp"
logger = MultilspyLogger()
lsp = SyncLanguageServer.create(config, logger, "/Users/aviavni/repos/JFalkorDB")

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

class Method:
    def __init__(self, node: Node):
        self.node = node
        self.calls = []
        self.parent = None

    def add_call(self, method: Self):
        self.calls.append(method)

class Class:
    def __init__(self, node: Node):
        self.node = node
        self.methods = {}

    def add_method(self, method: Method):
        method.parent = self
        self.methods[method.node] = method

class Interface:
    def __init__(self, node: Node):
        self.node = node
        self.methods = {}

    def add_method(self, method: Method):
        method.parent = self
        self.methods[method.node] = method

class Enum:
    def __init__(self, node: Node):
        self.node = node
        self.methods = {}

    def add_method(self, method: Method):
        method.parent = self
        self.methods[method.node] = method

def find_parent(node: Node, parent_types: list):
    while node.type not in parent_types:
        node = node.parent
    return node

with lsp.start_server():
    classes = {}
    trees = {}

    print("extract entities")
    for path in Path("/Users/aviavni/repos/JFalkorDB").rglob("*.java"):
        if 'test' in str(path):
            continue

        # Parse file
        source_code = path.read_bytes()
        tree = parser.parse(source_code)
        trees[str(path)] = tree

        query = JAVA_LANGUAGE.query("(class_declaration name: (identifier) @name) @definition.class")
        captures = query.captures(tree.root_node)
        if 'definition.class' in captures:
            for node in captures['definition.class']:
                classes[node] = Class(node)

        query = JAVA_LANGUAGE.query("(interface_declaration name: (identifier) @name) @definition.interface")
        captures = query.captures(tree.root_node)
        if 'definition.interface' in captures:
            for node in captures['definition.interface']:
                classes[node] = Interface(node)

        query = JAVA_LANGUAGE.query("(enum_declaration name: (identifier) @name) @definition.enum")
        captures = query.captures(tree.root_node)
        if 'definition.enum' in captures:
            for node in captures['definition.enum']:
                classes[node] = Enum(node)

        query = JAVA_LANGUAGE.query("(method_declaration name: (identifier) @name) @definition.method")
        captures = query.captures(tree.root_node)
        if 'definition.method' in captures:
            for node in captures['definition.method']:
                method_name = node.child_by_field_name('name').text
                method = Method(node)
                class_dec = find_parent(node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
                classes[class_dec].add_method(method)

        query = JAVA_LANGUAGE.query("(constructor_declaration name: (identifier) @name) @definition.method")
        captures = query.captures(tree.root_node)
        if 'definition.method' in captures:
            for node in captures['definition.method']:
                method_name = node.child_by_field_name('name').text
                method = Method(node)
                class_dec = find_parent(node, ['class_declaration', 'interface_declaration', 'enum_declaration'])
                classes[class_dec].add_method(method)

    print("extract calls")
    calls = 0
    for path, tree in trees.items():
        query = JAVA_LANGUAGE.query("(method_invocation name: (identifier) @name arguments: (argument_list)) @reference.call")
        captures = query.captures(tree.root_node)
        if 'reference.call' in captures:
            for caller in captures['reference.call']:
                locations = lsp.request_definition(str(path), caller.start_point.row, caller.start_point.column)
                for location in locations:
                    calls += 1
                    if location['absolutePath'] not in trees:
                        continue
                    callee_method_dec = trees[location['absolutePath']].root_node.descendant_for_point_range(Point(location['range']['start']['line'], location['range']['start']['character']), Point(location['range']['end']['line'], location['range']['end']['character']))
                    callee_method_dec = find_parent(callee_method_dec, ['method_declaration', 'constructor_declaration', 'field_declaration', 'enum_declaration', 'interface_declaration', 'class_declaration'])
                    if callee_method_dec.type in ['field_declaration', 'enum_declaration', 'interface_declaration', 'class_declaration']:
                        continue
                    callee_class_dec = find_parent(callee_method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
                    caller_method_dec = find_parent(caller, ['method_declaration', 'constructor_declaration'])
                    caller_class_dec = find_parent(caller_method_dec, ['class_declaration', 'interface_declaration', 'enum_declaration'])
                    classes[caller_class_dec].methods[caller_method_dec].add_call(classes[callee_class_dec].methods[callee_method_dec])

    print(calls)
    print("save to graph")
    graph = FalkorDB().select_graph("java")

    try:
        graph.delete()
    except:
        pass

    graph.create_node_range_index("Class", "name")
    graph.create_node_range_index("Method", "name")

    for class_dec, class_obj in classes.items():
        class_name = class_dec.child_by_field_name('name').text.decode('utf-8')
        graph.query("CREATE (n:Class {name: $name})", {"name": class_name})
        for method_dec, method_obj in class_obj.methods.items():
            method_name = method_dec.child_by_field_name('name').text.decode('utf-8')
            graph.query("MATCH (n:Class {name: $class_name}) CREATE (n)-[:HAS_METHOD]->(:Method {name: $name})", {"class_name": class_name, "name": method_name})
    
    for class_dec, class_obj in classes.items():
        caller_class_name = class_dec.child_by_field_name('name').text.decode('utf-8')
        for method_dec, method_obj in class_obj.methods.items():
            caller_method_name = method_dec.child_by_field_name('name').text.decode('utf-8')
            for call in method_obj.calls:
                callee_class_name = call.parent.node.child_by_field_name('name').text.decode('utf-8')
                callee_method_name = call.node.child_by_field_name('name').text.decode('utf-8')
                res = graph.query("""MATCH (:Class {name: $caller_class_name})-[:HAS_METHOD]->(caller:Method {name: $caller_method_name})
                            MATCH (:Class {name: $callee_class_name})-[:HAS_METHOD]->(callee:Method {name: $callee_method_name})
                            CREATE (caller)-[:CALLS]->(callee)""",
                            {"caller_class_name": caller_class_name, "caller_method_name": caller_method_name, "callee_class_name": callee_class_name, "callee_method_name": callee_method_name})
                print(res.relationships_created)