import os
import sys

def test_environment():
    print("CWD:", os.getcwd())
    print("PYTHON:", sys.executable)
    print("PATH:")
    for p in sys.path:
        print("  ", p)

    import src
    print("SRC:", src)
