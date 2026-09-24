# Changelog

All notable changes to `dbt-kinetica` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-09-24

First release published to PyPI.

### Changed

* Minimum Python version raised to 3.10 (current `dbt-core`, `dbt-adapters`
  and `gpudb` releases no longer support 3.9). Python 3.13 is now declared.
* Packaging metadata updated to the SPDX license expression format and the
  Apache-2.0 license text is now shipped in the sdist and wheel.
* Project URLs, changelog and GitHub Actions workflows (CI and PyPI publish)
  added.

## [1.0.0] - 2026-09-21

Initial release, validated against Kinetica 7.2.3.

### Added

* `table`, `view`, `incremental` (`append`, `delete+insert`, `microbatch`),
  `materialized_view`, `ephemeral`, `seed` and `snapshot` materializations.
* Metadata via the native `/show/schema` and `/show/table` endpoints.
* Kinetica-specific model configs: `replicated`, `ttl`, `table_properties`,
  `partition_by`, `tier_strategy`, `indexes`, `refresh`, `grants`.
* Cross-database macro overrides for Kinetica SQL.
* Unit tests, a dbt dry run against an in-memory fake server, and the official
  `dbt-tests-adapter` functional suite.

[1.0.1]: https://github.com/rosettadb/kinetica-dbt-adapter/compare/1.0.0...v1.0.1
[1.0.0]: https://github.com/rosettadb/kinetica-dbt-adapter/releases/tag/1.0.0
