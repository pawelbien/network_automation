# Network Automation

Multi-vendor network automation library in Python, designed for
integration with Nautobot Jobs. Currently supports Mikrotik
RouterOS.

## Features

-   Thin device clients per vendor
-   Action-based helpers: info, backup, upgrade
-   Factory for vendor selection
-   Pytest test suite with coverage
-   Ready for Nautobot Jobs integration

## Installation

``` bash
pip install -e ".[dev]"
```

## Usage

See update.py

## Tests

``` bash
python -m pytest --cov=network_automation --cov-report=term-missing
```

## License

MIT License.
