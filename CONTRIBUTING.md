# Contributing Guide

## Commit Message Format

This project follows [Conventional Commits](https://www.conventionalcommits.org/) specification for automatic changelog generation.

### Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc)
- **refactor**: A code change that neither fixes a bug nor adds a feature
- **perf**: A code change that improves performance
- **test**: Adding missing tests or correcting existing tests
- **build**: Changes that affect the build system or external dependencies
- **ci**: Changes to our CI configuration files and scripts
- **chore**: Other changes that don't modify src or test files
- **revert**: Reverts a previous commit

### Examples

```
feat: add brightness control for night mode
fix: resolve SSL certificate validation issue
docs: update README installation instructions
style: format code with prettier
refactor: simplify device discovery logic
test: add unit tests for config flow
chore: update dependencies
ci: add automated testing workflow
```

### Scopes (optional)

- `config`: Configuration related changes
- `ui`: User interface changes
- `api`: API related changes
- `deps`: Dependency updates

### Breaking Changes

To indicate breaking changes, add `BREAKING CHANGE:` in the footer or add `!` after the type:

```
feat!: change API endpoint structure

BREAKING CHANGE: The device API now returns different field names
```

## Automatic Changelog

The project uses GitHub Actions to automatically update the `CHANGELOG.md` file based on conventional commits. When you push to the `main` branch:

1. The action scans new commits since the last changelog update
2. Categorizes commits by type (feat → Added, fix → Fixed, etc.)
3. Updates the `[Unreleased]` section in `CHANGELOG.md`
4. Commits the changes back to the repository

## Manual Workflow Trigger

You can also manually trigger the changelog update by going to the Actions tab and running the "Update Changelog" workflow.