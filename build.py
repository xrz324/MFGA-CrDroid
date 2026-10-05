#!/usr/bin/env python3
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent
OEM_CONFIG = 'system/product/etc/fonts_customization.xml'
COLORLESS_FONTS = frozenset({'200.ttf', '300.ttf', '400.ttf', '700.ttf'})


def validate_fonts(root, fonts):
    # External references are intentionally provided by the target ROM, not the ZIP.
    external = json.loads((root / 'config/system-fonts.json').read_text())
    configs = {name: ET.parse(root / name).getroot()
               for name in ('fonts.xml', 'font_fallback.xml', OEM_CONFIG)}
    for name, document in configs.items():
        expected_tag = 'fonts-modification' if name == OEM_CONFIG else 'familyset'
        if document.tag != expected_tag:
            raise ValueError(f'{name}: expected {expected_tag}')
        font_dir = fonts / ('system/product/fonts' if name == OEM_CONFIG else 'system/fonts')
        for font in document.iter('font'):
            filename = (font.text or '').strip()
            if not filename or Path(filename).name != filename:
                raise ValueError(f'{name}: invalid font filename {filename!r}')
            if not (font_dir / filename).is_file() and filename not in external[name]:
                raise ValueError(f'{name}: missing module font or unknown system font {filename}')

    fallback = configs['font_fallback.xml']
    named = {family.get('name'): family for family in fallback.findall('family')
             if family.get('name')}
    for name in ('sans-serif', 'serif', 'monospace', 'roboto', 'roboto-flex'):
        if name not in named or not named[name].findall('font'):
            raise ValueError(f'Missing default family: {name}')
    names = [family.get('name') for family in configs[OEM_CONFIG]
             if family.tag in ('family', 'family-list')]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate OEM named family')
    required = set(json.loads((root / 'config/required-ui-families.json').read_text()))
    if not required.issubset(names):
        raise ValueError(f'Missing system UI families: {sorted(required - set(names))}')

    refs = [(font.text or '').strip() for font in fallback.iter('font')]
    for primary in ('200.ttf', '300.ttf', '400.ttf', '700.ttf'):
        if primary not in refs or not (fonts / 'system/fonts' / primary).is_file():
            raise ValueError(f'Missing primary font: {primary}')
    supplement = 'Unknown-symbol-supplementRegular.ttf'
    if supplement not in refs:
        raise ValueError(f'Missing symbol supplement: {supplement}')
    for emoji in ('NotoColorEmoji.ttf', 'NotoColorEmojiFlags.ttf'):
        if emoji not in refs or refs.index(emoji) > refs.index(supplement):
            raise ValueError(f'Emoji must precede symbol supplements: {emoji}')
    if refs[-1] != 'ZUno-Number.ttf':
        raise ValueError('Diagnostic glyph placeholders must be last')


def module_files(root, fonts):
    files = {name: root / name for name in
             ('fonts.xml', 'font_fallback.xml')}
    for name in ('action.sh', 'customize.sh'):
        files[name] = root / 'script' / name
    files[OEM_CONFIG] = root / OEM_CONFIG
    for path in (fonts / 'system').rglob('*'):
        if path.is_file():
            files[path.relative_to(fonts).as_posix()] = path
    for name in ('fonts.xml', 'font_fallback.xml'):
        files[f'system/etc/{name}'] = root / name
    return files


def prepare_upstream_fonts(root, staging):
    config = json.loads((root / 'config/upstream.json').read_text())
    checksum = config['sha256']
    if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError('Upstream SHA256 must contain 64 lowercase hexadecimal characters')
    archive = staging / 'upstream.zip'
    local_archive = os.environ.get('MFGA_UPSTREAM_ARCHIVE')
    if local_archive:
        shutil.copyfile(local_archive, archive)
    else:
        request = urllib.request.Request(config['url'], headers={'User-Agent': 'MFGA-CrDroid-build'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as target:
            shutil.copyfileobj(response, target)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != checksum:
        raise ValueError(f'Upstream archive SHA256 mismatch: {digest}')
    fonts_dir = staging / 'system/fonts'
    fonts_dir.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        prefix = config['font_prefix']
        if not prefix.endswith('/'):
            raise ValueError('Upstream font_prefix must end with /')
        entries = [entry for entry in package.infolist()
                   if entry.filename.startswith(prefix) and not entry.is_dir()]
        if not entries:
            raise ValueError('Upstream archive contains no fonts')
        for entry in entries:
            name = entry.filename
            filename = name[len(prefix):]
            if Path(filename).name != filename or not filename.endswith(('.ttf', '.otf', '.ttc')):
                raise ValueError(f'Unexpected upstream font entry: {name}')
            if filename == 'NotoColorEmoji-fallback.ttf':
                continue
            target = fonts_dir / filename
            if target.exists():
                raise ValueError(f'Duplicate upstream font entry: {name}')
            with package.open(entry) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    product_font = staging / 'system/product/fonts/Roboto-Regular.ttf'
    product_font.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fonts_dir / 'Roboto-Regular.ttf', product_font)


def remove_color_tables(font_path):
    """Return a copy with COLR/CPAL removed; the source font is never changed."""
    with TTFont(font_path) as font:
        for table in ('COLR', 'CPAL'):
            if table in font:
                del font[table]
        output = BytesIO()
        font.save(output)
    return output.getvalue()


def module_properties(root):
    metadata = json.loads((root / 'config/module.json').read_text())
    metadata['version'] = os.environ.get('MODULE_VERSION', 'dev-local')
    metadata['versionCode'] = os.environ.get('MODULE_VERSION_CODE', '1717180004')
    if not metadata['versionCode'].isascii() or not metadata['versionCode'].isdigit():
        raise ValueError('MODULE_VERSION_CODE must be a positive integer')
    if not 0 < int(metadata['versionCode']) <= 2147483647:
        raise ValueError('MODULE_VERSION_CODE is outside the supported integer range')
    for key, value in metadata.items():
        if not isinstance(value, str) or '\n' in value or '\r' in value:
            raise ValueError(f'Invalid module property: {key}')
    return ''.join(f'{key}={value}\n' for key, value in metadata.items())


def write_package(files, properties, output):
    for path in files.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.zip', delete=False) as file:
        temporary = Path(file.name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('module.prop', properties)
            for name, path in sorted(files.items()):
                if name.startswith('system/fonts/') and Path(name).name in COLORLESS_FONTS:
                    package.writestr(name, remove_color_tables(path))
                else:
                    package.write(path, name)
        with zipfile.ZipFile(temporary) as package:
            bad_entry = package.testzip()
            if bad_entry:
                raise ValueError(f'Corrupt archive entry: {bad_entry}')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def build_module(root=ROOT, output=None):
    properties = module_properties(root)
    with tempfile.TemporaryDirectory(prefix='mfga-build-') as temporary:
        fonts = Path(temporary)
        prepare_upstream_fonts(root, fonts)
        validate_fonts(root, fonts)
        return write_package(module_files(root, fonts), properties,
                             output or root / 'dist/MFGA-CrDroid.zip')


if __name__ == '__main__':
    print(build_module())
