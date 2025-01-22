import os
import unittest
from pathlib import Path

from api import SourceAnalyzer, File, Class, Function, Graph

class Test_PY_Analyzer(unittest.TestCase):
    def test_analyzer(self):
        path = Path(__file__).parent
        analyzer = SourceAnalyzer()
        print("\n=== Starting JS Analyzer Test ===")

        # Get the current file path
        current_file_path = os.path.abspath(__file__)
        print(f"Current file path: {current_file_path}")

        # Get the directory of the current file
        current_dir = os.path.dirname(current_file_path)
        print(f"Current directory: {current_dir}")

        # Append 'source_files/js' to the current directory
        path = os.path.join(current_dir, 'source_files')
        path = os.path.join(path, 'js')
        path = str(path)
        print(f"Test source files path: {path}")

        g = Graph("js")
        analyzer.analyze_local_folder(path, g)
        print("\nAnalysis complete. Checking results...")

        f = g.get_file('', 'src.js', '.js')
        expected_f = File('', 'src.js', '.js')
        print(f"\nChecking file: \nActual: {f}\nExpected: {expected_f}")
        self.assertEqual(expected_f, f)

        log_func = g.get_function_by_name('log')
        expected_log = Function('src.js', 'log', None, None, '', 0, 2)
        expected_log.add_argument('msg', 'Unknown')
        print(f"\nChecking log function: \nActual: {log_func}\nExpected: {expected_log}")
        self.assertEqual(expected_log, log_func)
        
        constructor = g.get_function_by_name('constructor')
        expected_constructor = Function('src.js', 'constructor', None, 'Task', '', 5, 9)
        expected_constructor.add_argument('name', 'Unknown')
        expected_constructor.add_argument('duration', 'Unknown')
        print(f"\nChecking constructor: \nActual: {constructor}\nExpected: {expected_constructor}")
        self.assertEqual(expected_constructor, constructor)

        abort = g.get_function_by_name('abort')
        expected_abort = Function('src.js', 'abort', None, None, '', 11, 14)
        expected_abort.add_argument('delay', 'Unknown')
        print(f"\nChecking abort function: \nActual: {abort}\nExpected: {expected_abort}")
        self.assertEqual(expected_abort, abort)

        task = g.get_class_by_name('Task')
        expected_task = Class('src.js', 'Task', None, 4, 15)
        print(f"\nChecking Task class: \nActual: {task}\nExpected: {expected_task}")
        self.assertEqual(expected_task, task)

        callees = g.function_calls(abort.id)
        print(f"\nChecking abort function callees: {[call.name for call in callees]}")
        self.assertEqual(len(callees), 1)
        self.assertEqual(callees[0], log_func)

        console_log_func = g.get_function_by_name('log')
        print(f"\nChecking console.log function: {console_log_func}")
        callers = g.function_called_by(console_log_func.id)
        callers = [caller.name for caller in callers]
        print(f"\nChecking console.log function callers: {callers}")

        self.assertIn('constructor', callers)
        self.assertIn('log', callers)
        
        print("\n=== JS Analyzer Test Complete ===")
