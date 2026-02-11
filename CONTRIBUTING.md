# Contributing to OpenShock Auto-Flasher

Thank you for your interest in contributing to OpenShock Auto-Flasher! We welcome contributions from the community. This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions with other contributors and maintainers.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:

- A clear, descriptive title
- A detailed description of the problem
- Steps to reproduce the issue
- Expected behavior vs. actual behavior
- Your environment details (OS, Python version, etc.)
- Any relevant logs or error messages

### Suggesting Enhancements

We welcome feature requests! When suggesting an enhancement:

- Use a clear, descriptive title
- Provide a detailed description of the proposed feature
- Explain why this enhancement would be useful
- List any alternatives you've considered

### Pull Requests

We actively welcome pull requests! Here's how to contribute code:

1. **Fork the repository** and create a new branch for your feature/fix
   ```bash
   git clone https://github.com/YOUR-USERNAME/OpenShock-AutoFlasher.git
   cd OpenShock-AutoFlasher
   git checkout -b feature/your-feature-name
   ```

2. **Set up your development environment**
   ```bash
   pip install -e .[dev]
   ```

3. **Make your changes** with clear, descriptive commit messages
   ```bash
   git commit -m "Add clear description of changes"
   ```

4. **Run tests and code quality checks**
   ```bash
   # Format code
   black openshock_autoflasher/ tests/
   
   # Lint code
   flake8 openshock_autoflasher/ tests/
   
   # Type check
   mypy openshock_autoflasher/
   
   # Run tests
   pytest tests/ -v
   ```

5. **All tests must pass** before submitting your PR

6. **Push to your fork** and submit a pull request
   ```bash
   git push origin feature/your-feature-name
   ```

## Development Guidelines

### Code Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Use [Black](https://github.com/psf/black) for code formatting (100 character line limit)
- Use [Flake8](https://flake8.pycqa.org/) for linting
- Use [Mypy](https://www.mypy-lang.org/) for type checking

### Type Hints

- Add type hints to all functions and methods
- Ensure your code passes mypy type checking
- Use the typing module for complex types

### Testing

- Write tests for new features and bug fixes
- Ensure all tests pass before submitting PR
- Aim for good test coverage
- Use pytest for testing framework

### Documentation

- Update documentation for new features
- Keep README.md current with changes
- Add docstrings to public functions and classes
- Update CHANGELOG.md with significant changes

## Pull Request Process

1. Ensure your PR description clearly describes the changes
2. Reference any related issues using `#issue-number`
3. Ensure all CI/CD checks pass
4. Wait for review from maintainers
5. Be responsive to feedback and requests for changes
6. Your PR will be merged once it's approved

## Project Structure

```
openshock_autoflasher/
├── __init__.py           # Package initialization
├── __main__.py           # Entry point for module
├── cli.py                # Command-line interface
├── flasher.py            # Core flashing logic
├── constants.py          # Configuration constants
├── styles.py             # Terminal styling
└── py.typed              # PEP 561 marker

tests/
├── test_cli.py           # CLI tests
├── test_flasher.py       # Flasher tests
├── test_constants.py     # Constants tests
└── test_styles.py        # Styles tests
```

## Questions?

Feel free to open an issue for any questions or discussions about contributing!

## License

By contributing to OpenShock Auto-Flasher, you agree that your contributions will be licensed under the AGPL-3.0 License.
