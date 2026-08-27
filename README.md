# BlueWhale Code

BlueWhale Code is an evidence-driven coding agent powered by DeepSeek. It is being built
from first principles for the NJU Software Engineering recommendation assessment.

The first milestone provides the Python package and CLI contract. Agent execution and the
local Web GUI will be added in later, independently tested modules.

## Development

BlueWhale requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

The local application will be started with:

```bash
bluewhale serve --workspace /path/to/project
```

Do not place API keys in the repository. DeepSeek credentials will be read from the
`DEEPSEEK_API_KEY` environment variable when the provider module is implemented.

