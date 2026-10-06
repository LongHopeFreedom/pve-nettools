# [CHANGE] 2026-08-02 入口維持薄層，避免不可 import 的 python -m 路徑藏有分派邏輯。
import sys

from . import cli

sys.exit(cli.main(sys.argv[1:]))
