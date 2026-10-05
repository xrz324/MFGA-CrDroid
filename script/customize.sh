SKIPUNZIP=0

[ "$API" -ge 33 ] || abort "MFGA-CrDroid requires Android 13 or newer."
if [ -n "$MAGISK_VER_CODE" ] && [ "$MAGISK_VER_CODE" -lt 28000 ]; then
  abort "Magisk 28.0 or newer is required."
fi
if [ -n "$KSU_VER_CODE" ] && [ "$KSU_VER_CODE" -lt 11986 ]; then
  abort "KernelSU 11986 or newer is required."
fi
if [ -n "$KSU_KERNEL_VER_CODE" ] && [ "$KSU_KERNEL_VER_CODE" -lt 11986 ]; then
  abort "KernelSU kernel 11986 or newer is required."
fi
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/action.sh" 0 0 0755

copy_config() {
  config_source="$MODPATH/$1"
  config_target="$MODPATH/system/$2"
  [ -f "$config_source" ] || abort "Missing font configuration: $1"
  mkdir -p "${config_target%/*}" || abort "Cannot create font configuration directory."
  cp -f "$config_source" "$config_target" || abort "Cannot install font configuration: $1"
}

copy_config fonts.xml etc/fonts.xml
if [ -f /system/etc/font_fallback.xml ]; then
  copy_config font_fallback.xml etc/font_fallback.xml
fi
ui_print "- MFGA-CrDroid installed."
