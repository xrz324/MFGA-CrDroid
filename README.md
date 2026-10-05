# MFGA-CrDroid

English | [简体中文](README_zh-CN.md)

## Overview

This fork is an independently maintained font module for crDroid, supporting only crDroid 13 and newer. It includes font configuration fixes for Android 17 and crDroid 13+. It will periodically sync with MFGA upstream and adapt to changes in the crDroid source code.

## Changes

Running Action immediately stops Google apps, disables GMS font services, and clears font caches. WebUI and compatibility with Chinese vendor-customized ROMs are not included. During the build, color tables are removed from the installation copies of text fonts.

Fonts are downloaded from the MFGA upstream release pinned in `config/upstream.json` and combined with this project's font configurations.

## Notes

- When used with NoMount, no adjustments to default unmount or kernel unmount settings are needed.
- FontLoader is only required alongside NoMount when specific app exclusions are configured.

Untested usage or combinations may cause issues; evaluate them before use.

## Build

Install the dependencies listed in `requirements-build.txt`, then run `python3 build.py`.
The module is generated at `dist/MFGA-CrDroid.zip`. An Internet connection is required for the build; set `MFGA_UPSTREAM_ARCHIVE` to a local copy of the pinned release to build offline. The SHA256 check still applies.

## Source

Upstream: [Numbersf/MakeFontsGreatAgain](https://github.com/Numbersf/MakeFontsGreatAgain). Font sources and licenses are listed in [LICENSES.md](LICENSES.md). Thanks to the upstream project.
