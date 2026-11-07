"""Text shared by the ``web_search`` and ``web_fetch`` tools.

| name           | contract                                                        |
|----------------|-----------------------------------------------------------------|
| ``NOTICE``     | first line of every tool result: the content is untrusted data  |
| ``USER_AGENT`` | ``user-agent`` header of every outgoing request                 |
"""

from pyharness import package_prompts

PROMPTS = package_prompts(__file__)
NOTICE: str = PROMPTS["common"]["notice"]
USER_AGENT = "pyharness/0.1 (+https://github.com/pyharness)"
