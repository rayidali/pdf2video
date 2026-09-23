"""Static checks on generated Manim code. Pure AST and regex; nothing is executed."""
import ast
import re

BANNED = [
    (r"\bMathTex\b|\bTex\s*\(", "LaTeX (MathTex/Tex) is not available on the renderer; use Text()"),
    (r"\bImageMobject\b|\bSVGMobject\b", "external image assets are not allowed"),
    (r"\bThreeDScene\b|\bThreeDAxes\b|\bMovingCameraScene\b", "3D and moving-camera scenes are not allowed"),
    (r"\bimport\s+random\b|\bnp\.random\b|\bnumpy\.random\b", "randomness is not allowed"),
    (r"\bimport\s+os\b|\bsubprocess\b|\bopen\s*\(|\b__import__\b|\beval\s*\(|\bexec\s*\(", "filesystem/process access is not allowed"),
]


def validate_code(code: str, expected_class: str) -> list[str]:
    """Return a list of human-readable problems. Empty list means the code passed."""
    errors: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append(f"[SYNTAX] line {e.lineno}: {e.msg}")
        return errors

    if "from manim import" not in code:
        errors.append("[IMPORT] missing 'from manim import *'")

    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    names = [c.name for c in classes]
    if expected_class not in names:
        errors.append(f"[CLASS] expected class '{expected_class}', found {names or 'none'}")
    for c in classes:
        if c.name == expected_class and not any(isinstance(n, ast.FunctionDef) and n.name == "construct" for n in c.body):
            errors.append(f"[METHOD] class '{c.name}' has no construct() method")

    for pattern, message in BANNED:
        if re.search(pattern, code):
            errors.append(f"[BANNED] {message}")
    return errors


def format_error_report(code: str, errors: list[str]) -> str:
    report = "The Manim code has the following problems:\n\n"
    report += "\n".join(f"{i}. {e}" for i, e in enumerate(errors, 1))
    report += "\n\n--- CODE ---\n" + code + "\n--- END CODE ---\n"
    return report
