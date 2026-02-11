# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version               | Supported  |
|-----------------------|------------|
| GitHub main branch    | ✅ Yes     |
| PyPI releases         | ⚠️ Limited |
| External Forks        | ❌ No      |
| Other Github Branches | ❌ No      |

## Reporting a Vulnerability

### Using GitHub's Security Advisory System (Recommended)

The preferred way to report security vulnerabilities is through GitHub's private vulnerability reporting feature:

1. Go to the [Security tab](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/security) of this repository
2. Click on "Report a vulnerability" in the left sidebar
3. Fill out the vulnerability report form
4. Submit your report

This automatically creates a private discussion between you and the maintainers, ensuring the vulnerability is handled confidentially before public disclosure.

Please include:

- Description of the vulnerability
- Steps to reproduce (if applicable)
- Potential impact
- Suggested fix (if you have one)

### Response Process

We will:

1. Acknowledge receipt of your report at our soonest avalibility
2. Investigate and determine severity
3. Work on a fix and security patch
4. Coordinate a responsible disclosure timeline
5. Credit you in the security advisory (unless you prefer anonymity)

## Security Best Practices

When using OpenShock Auto-Flasher:

- Keep Python and dependencies up to date
- Use the latest version of the tool
- Verify device integrity before flashing
- Review firmware sources carefully

## Dependencies

We monitor our dependencies for security vulnerabilities:

- `esptool` - ESP32 flashing tool
- `pyserial` - Serial port communication
- `requests` - HTTP library
- `rich` - Terminal styling

We do our best to keep these dependencies updated and respond quickly to security advisories.

## Questions?

For security-related questions (non-vulnerability), please contact the maintainer.
