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
from fontTools import subset
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = Path(__file__).resolve().parent
OEM_CONFIG = 'system/product/etc/fonts_customization.xml'
# Preserve the original font-to-weight mapping.
PRIMARY_WEIGHTS = {
    100: '200.ttf', 200: '200.ttf', 300: '300.ttf',
    400: '400.ttf', 500: '400.ttf', 600: '700.ttf',
    700: '700.ttf', 800: '700.ttf', 900: '700.ttf',
}
COLORLESS_FONTS = frozenset(PRIMARY_WEIGHTS.values())
# Pinned upstream filenames are not their OpenType weights.
PRIMARY_SOURCE_WEIGHTS = {'200.ttf': 400, '300.ttf': 650, '400.ttf': 700, '700.ttf': 900}
# Match each installed file's intrinsic style to its intended module slot.
# Typeface may derive a named family's base weight from this metadata, not XML.
PRIMARY_STYLE_WEIGHTS = {'200.ttf': 200, '300.ttf': 300, '400.ttf': 400, '700.ttf': 700}
METRIC_PROFILES = json.loads((ROOT / 'config/metric-fonts.json').read_text())
PRODUCT_METRIC_FONTS = frozenset(METRIC_PROFILES)
VARIABLE_FONTS = frozenset({'Roboto-Regular.ttf', 'RobotoFlex-Regular.ttf'}) | PRODUCT_METRIC_FONTS
OVERFLOW_FONTS = {filename: f'MFGAOverflow-{filename}' for filename in COLORLESS_FONTS}
# Framework families register static glyphs; legacy XML retains variable providers.
LEGACY_METRIC_FAMILIES = {
    'sans-serif': 'Roboto-Regular.ttf', 'sans-serif-condensed': 'Roboto-Regular.ttf',
    'roboto': 'Roboto-Regular.ttf', 'roboto-flex': 'RobotoFlex-Regular.ttf',
}


def family_signature(family):
    return [(font.attrib, (font.text or '').strip(),
             [(axis.attrib) for axis in font.findall('axis')])
            for font in family.findall('font')]


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
            source_name = filename.removeprefix('MFGAOverflow-')
            if source_name in COLORLESS_FONTS:
                if not (font_dir / filename).is_file():
                    raise ValueError(f'{name}: missing primary font {filename}')
                weight = int(font.get('weight', '400'))
                if PRIMARY_WEIGHTS.get(weight) != source_name:
                    raise ValueError(f'{name}: incorrect primary weight {weight}: {filename}')
                if font.findall('axis') or font.get('supportedAxes'):
                    raise ValueError(f'{name}: static primary font declares variable axes: {filename}')

    legacy_named = {family.get('name'): family for family in configs['fonts.xml'].findall('family')
                    if family.get('name')}

    fallback = configs['font_fallback.xml']
    named = {family.get('name'): family for family in fallback.findall('family')
             if family.get('name')}
    for name in ('sans-serif', 'sans-serif-condensed', 'serif', 'monospace', 'roboto', 'roboto-flex'):
        if name not in named or not named[name].findall('font'):
            raise ValueError(f'Missing default family: {name}')
    expected = [(str(weight), filename) for weight, filename in PRIMARY_WEIGHTS.items()]
    static_signature = [({'weight': weight, 'style': 'normal'}, filename, [])
                        for weight, filename in expected]
    for name, family in named.items():
        legacy = legacy_named.get(name)
        if name in LEGACY_METRIC_FAMILIES:
            provider = LEGACY_METRIC_FAMILIES[name]
            if legacy is None or {(font.text or '').strip() for font in legacy} != {provider}:
                raise ValueError(f'fonts.xml: missing metric provider for {name}')
            if family_signature(family) != static_signature:
                raise ValueError(f'font_fallback.xml: incomplete direct primary registration for {name}')
        elif legacy is None or family_signature(legacy) != family_signature(family):
            raise ValueError(f'Inconsistent primary family between font configurations: {name}')

    # Keep the default first and preserve the weighted fallback for other named
    # families (including Product providers), plus the full tall-symbol coverage.
    for document_name in ('fonts.xml', 'font_fallback.xml'):
        document = configs[document_name]
        first = next(iter(document))
        if first.tag != 'family' or first.get('name') != 'sans-serif':
            raise ValueError(f'{document_name}: default sans-serif family must be first')
        candidates = [family for family in document.findall('family') if not family.attrib]
        if not any([(font.get('weight'), (font.text or '').strip())
                    for font in family.findall('font')] == expected for family in candidates):
            raise ValueError(f'{document_name}: missing weighted primary glyph fallback')
        overflow_expected = [(weight, OVERFLOW_FONTS[filename]) for weight, filename in expected]
        if not any([(font.get('weight'), (font.text or '').strip())
                    for font in family.findall('font')] == overflow_expected for family in candidates):
            raise ValueError(f'{document_name}: missing tall-symbol glyph fallback')
    names = [family.get('name') for family in configs[OEM_CONFIG]
             if family.tag in ('family', 'family-list')]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate OEM named family')
    required = set(json.loads((root / 'config/required-ui-families.json').read_text()))
    if not required.issubset(names):
        raise ValueError(f'Missing system UI families: {sorted(required - set(names))}')
    for family in configs[OEM_CONFIG]:
        if family.get('name') in required:
            refs = {(font.text or '').strip() for font in family.iter('font')}
            if not refs or not refs.issubset(PRODUCT_METRIC_FONTS):
                raise ValueError(f'System UI family must retain variable providers: {family.get("name")}')

    # Validate the actual fvar tables, not just whether XML contains axis tags.
    for document_name, document in configs.items():
        directory = 'system/product/fonts' if document_name == OEM_CONFIG else 'system/fonts'
        for filename in VARIABLE_FONTS:
            references = [font for font in document.iter('font')
                          if (font.text or '').strip() == filename]
            if not references:
                continue
            with TTFont(fonts / directory / filename, lazy=True) as font_file:
                axes = {axis.axisTag: axis for axis in font_file['fvar'].axes}
                for reference in references:
                    for tag in filter(None, reference.get('supportedAxes', '').split(',')):
                        if tag not in axes:
                            raise ValueError(f'{document_name}: {filename} has no {tag} axis')
                    for axis in reference.findall('axis'):
                        tag, value = axis.get('tag'), float(axis.get('stylevalue'))
                        if tag not in axes or not axes[tag].minValue <= value <= axes[tag].maxValue:
                            raise ValueError(f'{document_name}: invalid {tag} axis for {filename}')

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


def validate_conversion(root, fonts):
    prefix = json.loads((root / 'config/upstream.json').read_text())['font_prefix']
    style_mask = (1 << 0) | (1 << 5) | (1 << 6) | (1 << 7) | (1 << 9)
    with zipfile.ZipFile(fonts / 'upstream.zip') as upstream:
        for filename, weight in PRIMARY_STYLE_WEIGHTS.items():
            with TTFont(BytesIO(upstream.read(prefix + filename))) as source:
                cmap = source.getBestCmap()
                scale = source['head'].unitsPerEm / 2048
                ascent, descent = round(1900 * scale), round(-500 * scale)
                top, bottom = round(2163 * scale), round(-555 * scale)
                ordinary = {cp for cp, name in cmap.items()
                            if not source['glyf'][name].numberOfContours
                            or (source['glyf'][name].yMax <= top and source['glyf'][name].yMin >= bottom)}
                for converted, coverage in ((filename, ordinary), (OVERFLOW_FONTS[filename], set(cmap))):
                    with TTFont(fonts / 'system/fonts' / converted) as font:
                        if set(font.getBestCmap()) != coverage:
                            raise ValueError(f'{converted}: converted glyph coverage changed')
                        if any(tag in font for tag in ('COLR', 'CPAL', 'fvar')):
                            raise ValueError(f'{converted}: expected colorless static glyphs')
                        selection = (1 << 5 if weight >= 700 else 1 << 6) | (1 << 7)
                        if (font['OS/2'].usWeightClass != weight
                                or font['OS/2'].version < 4
                                or (font['OS/2'].fsSelection & style_mask) != selection
                                or (font['head'].macStyle & 3) != int(weight >= 700)):
                            raise ValueError(f'{converted}: incorrect converted style')
                        if font['head'].unitsPerEm != source['head'].unitsPerEm:
                            raise ValueError(f'{converted}: glyph scale changed during conversion')
                        expected = (ascent, descent, 0)
                        if converted != filename:
                            expected = (max(ascent, font['head'].yMax), min(descent, font['head'].yMin), 0)
                        if ((font['hhea'].ascent, font['hhea'].descent, font['hhea'].lineGap) != expected
                                or (font['OS/2'].sTypoAscender, font['OS/2'].sTypoDescender,
                                    font['OS/2'].sTypoLineGap) != expected):
                            raise ValueError(f'{converted}: incorrect converted line metrics')
                        if (font['OS/2'].usWinAscent < max(expected[0], font['head'].yMax)
                                or font['OS/2'].usWinDescent < max(-expected[1], -font['head'].yMin)):
                            raise ValueError(f'{converted}: clipping bounds do not cover glyphs')
                        for cp, name in font.getBestCmap().items():
                            original = cmap[cp]
                            if (font['hmtx'][name] != source['hmtx'][original]
                                    or font['glyf'][name].getCoordinates(font['glyf'])
                                    != source['glyf'][original].getCoordinates(source['glyf'])):
                                raise ValueError(f'{converted}: glyph U+{cp:04X} changed during conversion')

    for filename, profile in METRIC_PROFILES.items():
        with TTFont(fonts / 'system/product/fonts' / filename) as font:
            fields = {'head': dict(profile['bounds'], unitsPerEm=profile['unitsPerEm'],
                                   macStyle=profile['macStyle']),
                      'hhea': profile['hhea'], 'OS/2': profile['os2'], 'post': profile['post']}
            for table, values in fields.items():
                for field, expected in values.items():
                    if getattr(font[table], field) != expected:
                        raise ValueError(f'{filename}: incorrect converted {table}.{field}')
            axes = [(axis.axisTag, axis.minValue, axis.defaultValue, axis.maxValue)
                    for axis in font['fvar'].axes]
            if axes != [tuple(axis) for axis in profile['axes']]:
                raise ValueError(f'{filename}: incorrect converted variable axes')
            if (set(font.getBestCmap()) != {0xFFFF}
                    or any(font['glyf'][name].numberOfContours for name in font.getGlyphOrder())):
                raise ValueError(f'{filename}: metric provider contains visible glyphs')


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
    # Product XML resolves paths under /product/fonts, not /system/fonts.
    product_fonts = staging / 'system/product/fonts'
    product_fonts.mkdir(parents=True, exist_ok=True)
    for filename, profile in METRIC_PROFILES.items():
        create_metric_font(profile, filename, product_fonts / filename)
    for filename in sorted(COLORLESS_FONTS):
        primary, overflow = split_text_font(prepare_text_font(fonts_dir / filename))
        (fonts_dir / filename).write_bytes(primary)
        (fonts_dir / OVERFLOW_FONTS[filename]).write_bytes(overflow)


def create_metric_font(profile, filename, output):
    """Build an empty provider from numeric ROM metrics, without bundling ROM glyphs."""
    builder = FontBuilder(profile['unitsPerEm'], isTTF=True)
    glyphs = ['.notdef', 'uniFFFF']
    builder.setupGlyphOrder(glyphs)
    builder.setupCharacterMap({0xFFFF: 'uniFFFF'})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in glyphs})
    builder.setupHorizontalMetrics({name: (0, 0) for name in glyphs})
    builder.setupHorizontalHeader(**profile['hhea'])
    builder.setupOS2(version=4, **profile['os2'])
    builder.setupNameTable({'familyName': 'MFGA Layout ' + Path(filename).stem,
                            'styleName': 'Italic' if profile['macStyle'] & 2 else 'Regular',
                            'psName': 'MFGALayout-' + Path(filename).stem})
    builder.setupPost(**profile['post'])
    builder.setupFvar([(*axis, axis[0]) for axis in profile['axes']], [])
    builder.setupGvar({name: [] for name in glyphs})
    # Empty glyphs have no outlines to recompute. Keep the source's layout box.
    builder.font.recalcBBoxes = False
    for field, value in profile['bounds'].items():
        setattr(builder.font['head'], field, value)
    builder.font['head'].macStyle = profile['macStyle']
    builder.save(output)


def prepare_text_font(font_path):
    """Preserve glyphs while correcting intrinsic styles and Roboto line metrics."""
    with TTFont(font_path) as font:
        expected_weight = PRIMARY_SOURCE_WEIGHTS[font_path.name]
        if font['OS/2'].usWeightClass != expected_weight:
            raise ValueError(f'{font_path.name}: upstream weight changed; review primary mappings')
        for table in ('COLR', 'CPAL'):
            if table in font:
                del font[table]
        # XML controls matching, but Typeface::createFromFamilies also reads
        # SkTypeface's intrinsic style to initialize the family's base weight.
        # In particular, the source 400.ttf is internally 700/Bold. Leaving it
        # unchanged makes NORMAL inherit 700 and select the heavier 700.ttf.
        style_weight = PRIMARY_STYLE_WEIGHTS[font_path.name]
        bold = style_weight >= 700
        font['OS/2'].usWeightClass = style_weight
        font['OS/2'].fsSelection = ((font['OS/2'].fsSelection & ~((1 << 5) | (1 << 6)))
                                   | (1 << 5 if bold else 1 << 6))
        font['head'].macStyle = (font['head'].macStyle & ~1) | int(bold)
        # NEW/system/fonts/Roboto-Regular.ttf: 1900/-500/0 at 2048 UPEM.
        # Match hhea and typo consumers without shifting or scaling glyph outlines.
        scale = font['head'].unitsPerEm / 2048
        ascent, descent = round(1900 * scale), round(-500 * scale)
        font['hhea'].ascent, font['hhea'].descent = ascent, descent
        font['hhea'].lineGap = 0
        font['OS/2'].sTypoAscender, font['OS/2'].sTypoDescender = ascent, descent
        font['OS/2'].sTypoLineGap = 0
        font['OS/2'].version = max(4, font['OS/2'].version)
        font['OS/2'].fsSelection |= 1 << 7  # USE_TYPO_METRICS: consistent line spacing.
        # Keep usWinAscent/usWinDescent and glyph bounds for clipping safety.
        output = BytesIO()
        font.save(output)
    return output.getvalue()


def split_text_font(data):
    """Keep tall symbols available without inflating every ordinary text box."""
    with TTFont(BytesIO(data)) as font:
        cmap = font.getBestCmap()
        scale = font['head'].unitsPerEm / 2048
        top, bottom = round(2163 * scale), round(-555 * scale)
        tall = set()
        for codepoint, name in cmap.items():
            glyph = font['glyf'][name]
            if glyph.numberOfContours and (glyph.yMax > top or glyph.yMin < bottom):
                tall.add(codepoint)
        # Full coverage in overflow also preserves combining-mark clusters with
        # arbitrary bases. Its larger metrics apply only when it is selected.
        for record in font['name'].names:
            if record.nameID in (1, 3, 4, 6, 16):
                value = record.toUnicode() + ('-Overflow' if record.nameID == 6 else ' Overflow')
                record.string = value.encode(record.getEncoding())
        ascent = max(font['hhea'].ascent, font['head'].yMax)
        descent = min(font['hhea'].descent, font['head'].yMin)
        font['hhea'].ascent, font['hhea'].descent = ascent, descent
        font['OS/2'].sTypoAscender, font['OS/2'].sTypoDescender = ascent, descent
        font['OS/2'].usWinAscent, font['OS/2'].usWinDescent = ascent, -descent
        overflow = BytesIO()
        font.save(overflow)
    with TTFont(BytesIO(data)) as font:
        options = subset.Options()
        options.layout_features = ['*']
        options.name_IDs = ['*']
        options.name_legacy = True
        options.name_languages = ['*']
        options.recalc_bounds = True
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=set(font.getBestCmap()) - tall)
        subsetter.subset(font)
        # Preserve true bounds, including any unencoded layout alternates kept
        # by GSUB closure. Prefer typo metrics for line spacing, not these bounds.
        glyphs = [font['glyf'][name] for name in font.getGlyphOrder()]
        font['OS/2'].usWinAscent = max(font['hhea'].ascent,
                                      max((getattr(g, 'yMax', 0) for g in glyphs), default=0))
        font['OS/2'].usWinDescent = max(-font['hhea'].descent,
                                       -min((getattr(g, 'yMin', 0) for g in glyphs), default=0))
        primary = BytesIO()
        font.save(primary)
    return primary.getvalue(), overflow.getvalue()


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
        validate_conversion(root, fonts)
        return write_package(module_files(root, fonts), properties,
                             output or root / 'dist/MFGA-CrDroid.zip')


if __name__ == '__main__':
    print(build_module())
