"""Allow ``python -m funhou_hook`` to behave like the hook entrypoint."""

from .hook import main

raise SystemExit(main())
