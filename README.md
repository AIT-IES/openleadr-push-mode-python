# OpenLEADR PUSH Mode

This Python3 package builds upon [OpenLEADR](https://github.com/openleadr/openleadr-python) to implement OpenADR servers and clients in PUSH mode.

## Examples

Simple examples for using VTN (server) and VEN (client) in PUSH mode can be found in folder [examples](./examples).

## Testing

```
pip install -r dev_requirements.txt
pytest
```

## Code style

Compliance with OpenLEADR code style is guaranteed via [flake8](https://flake8.pycqa.org/en/latest/index.html#):

```
flake8 openleadr_push_mode/ --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 openleadr_push_mode/ --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```