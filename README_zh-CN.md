# MFGA-CrDroid

[English](README.md) | 简体中文

## 概述

该 Fork 是为 crDroid 独立维护的字体模块，仅支持 crDroid 13 及更高版本，包含针对 Android 17 和 crDroid 13+ 的字体配置修正，将不定期同步 MFGA 上游并适配 crDroid 源码变动。

## 变更

执行 Action 会直接关闭谷歌系应用，禁用 GMS 字体服务并清理字体缓存，无 WebUI 和国产定制系统适配，构建时会对文本字体的安装副本移除颜色表。

字体来自 `config/upstream.json` 固定的 MFGA 上游 Release，下载后与本项目的字体配置整合。

## 注意

- 与 NoMount 配合使用时，无须调整默认卸载或内核卸载设置。
- 仅当存在指定应用排除时，需与 FontLoader 叠加使用。

未经测试的用法或搭配可能造成问题，请评估后使用。

## 构建

安装 `requirements-build.txt` 所需依赖，然后运行 `python3 build.py`。
产物为 `dist/MFGA-CrDroid.zip`，构建需要网络；可设置 `MFGA_UPSTREAM_ARCHIVE` 指向固定版本 的本地副本进行离线构建，仍会校验 SHA256。

## 来源

原项目：[Numbersf/MakeFontsGreatAgain](https://github.com/Numbersf/MakeFontsGreatAgain)。字体来源与许可见 [LICENSES.md](LICENSES.md)。在此致谢。
