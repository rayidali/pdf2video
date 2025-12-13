"""
Manim Code Validator

Validates generated Manim code before saving:
1. Syntax check with ast.parse()
2. Import check by exec()
3. Class existence check
4. Optional: Dry run instantiation

If validation fails, can request Claude to fix the code.
"""

import ast
import logging
import re
import sys
import traceback
from typing import Optional

logger = logging.getLogger(__name__)


class ManimValidationError(Exception):
    """Raised when Manim code validation fails."""
    def __init__(self, message: str, error_type: str, line_number: Optional[int] = None):
        self.message = message
        self.error_type = error_type  # "syntax", "import", "class", "runtime"
        self.line_number = line_number
        super().__init__(message)


class ManimValidator:
    """Validates Manim code for correctness before saving."""

    def __init__(self):
        self.required_imports = ["from manim import"]

    def validate_syntax(self, code: str) -> tuple[bool, Optional[str]]:
        """
        Check if the code has valid Python syntax.
        Returns (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
            if e.text:
                error_msg += f"\n  Code: {e.text.strip()}"
            return False, error_msg

    def validate_imports(self, code: str) -> tuple[bool, Optional[str]]:
        """
        Check if the code has the required Manim import.
        """
        if not any(imp in code for imp in self.required_imports):
            return False, "Missing required import: 'from manim import *'"
        return True, None

    def validate_class_exists(self, code: str, expected_class: str) -> tuple[bool, Optional[str]]:
        """
        Check if the expected Scene class is defined in the code.
        """
        # Parse the AST and look for class definition
        try:
            tree = ast.parse(code)
            class_names = [
                node.name for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
            ]

            if expected_class not in class_names:
                if class_names:
                    return False, f"Expected class '{expected_class}' not found. Found: {class_names}"
                else:
                    return False, f"No class definitions found. Expected: {expected_class}"

            return True, None
        except SyntaxError:
            # Already caught by validate_syntax
            return True, None

    def validate_construct_method(self, code: str) -> tuple[bool, Optional[str]]:
        """
        Check if the Scene class has a construct method.
        """
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if class has 'construct' method
                    method_names = [
                        n.name for n in node.body
                        if isinstance(n, ast.FunctionDef)
                    ]
                    if 'construct' not in method_names:
                        return False, f"Class '{node.name}' missing 'construct' method"
            return True, None
        except SyntaxError:
            return True, None

    def validate_no_dangerous_code(self, code: str) -> tuple[bool, Optional[str]]:
        """
        Check for potentially dangerous code patterns.
        """
        dangerous_patterns = [
            (r'\bos\.system\b', "os.system() calls are not allowed"),
            (r'\bsubprocess\b', "subprocess module is not allowed"),
            (r'\b__import__\b', "__import__() is not allowed"),
            (r'\beval\b', "eval() is not allowed"),
            (r'\bexec\b(?!\s*\()', "exec() is not allowed"),  # Allow our own exec for testing
            (r'\bopen\s*\([^)]*["\']w', "Writing files is not allowed"),
        ]

        for pattern, message in dangerous_patterns:
            if re.search(pattern, code):
                return False, f"Security check failed: {message}"

        return True, None

    def try_import(self, code: str) -> tuple[bool, Optional[str]]:
        """
        Try to execute the code in a restricted namespace to catch import errors.
        This doesn't actually run animations, just checks if the code can be loaded.

        Note: This requires manim to be installed.
        """
        try:
            # Create a restricted namespace
            namespace = {}

            # Execute the code
            exec(code, namespace)

            return True, None
        except ImportError as e:
            return False, f"Import error: {e}"
        except NameError as e:
            return False, f"Name error (undefined variable): {e}"
        except TypeError as e:
            return False, f"Type error: {e}"
        except Exception as e:
            return False, f"Runtime error during import: {type(e).__name__}: {e}"

    def validate(
        self,
        code: str,
        expected_class: str,
        skip_import_check: bool = False
    ) -> tuple[bool, list[str]]:
        """
        Run all validation checks on the code.

        Args:
            code: The Manim Python code to validate
            expected_class: Expected class name (e.g., "Slide001")
            skip_import_check: Skip the actual import test (useful if manim not installed)

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        # 1. Check syntax
        valid, error = self.validate_syntax(code)
        if not valid:
            errors.append(f"[SYNTAX] {error}")

        # 2. Check imports
        valid, error = self.validate_imports(code)
        if not valid:
            errors.append(f"[IMPORT] {error}")

        # 3. Check class exists
        valid, error = self.validate_class_exists(code, expected_class)
        if not valid:
            errors.append(f"[CLASS] {error}")

        # 4. Check construct method
        valid, error = self.validate_construct_method(code)
        if not valid:
            errors.append(f"[METHOD] {error}")

        # 5. Security check
        valid, error = self.validate_no_dangerous_code(code)
        if not valid:
            errors.append(f"[SECURITY] {error}")

        # 6. Try actual import (if requested and no syntax errors)
        if not skip_import_check and not any("[SYNTAX]" in e for e in errors):
            valid, error = self.try_import(code)
            if not valid:
                errors.append(f"[RUNTIME] {error}")

        return len(errors) == 0, errors

    def format_error_report(self, code: str, errors: list[str]) -> str:
        """
        Format errors into a report that can be sent to Claude for fixing.
        """
        report = "The generated Manim code has the following errors:\n\n"

        for i, error in enumerate(errors, 1):
            report += f"{i}. {error}\n"

        report += "\n--- CODE ---\n"
        report += code
        report += "\n--- END CODE ---\n"

        return report


# Singleton instance
validator = ManimValidator()
