#!/system/bin/sh

# This action is explicit: stop font consumers, disable GMS font delivery, clear its caches.
command -v pm >/dev/null 2>&1 || { echo "Package manager is unavailable."; exit 1; }
users=$(pm list users) || exit 1
users=$(printf '%s\n' "$users" | sed -n 's/.*UserInfo{\([0-9][0-9]*\):.*/\1/p')
[ -n "$users" ] || { echo "No Android users found."; exit 1; }
status=0
found=0
for user_id in $users; do
  if ! pm path --user "$user_id" com.google.android.gms 2>/dev/null | grep -q '^package:'; then
    continue
  fi
  found=1
  echo "Processing GMS fonts for user $user_id..."
  for app in com.android.chrome com.google.android.gm; do
    am force-stop --user "$user_id" "$app" || status=1
  done
  for component in update.UpdateSchedulerService provider.FontsProvider; do
    pm disable --user "$user_id" "com.google.android.gms/com.google.android.gms.fonts.$component" || status=1
  done
  for data_root in /data/user /data/user_de; do
    cache="$data_root/$user_id/com.google.android.gms/files/fonts"
    if [ -d "$cache" ]; then
      rm -rf -- "$cache" || status=1
    fi
  done
done
if [ "$found" -eq 0 ]; then
  echo "GMS is not installed; no font processing needed."
  exit 0
fi
# Keep the original action's system font-cache cleanup, including hidden entries.
if [ -d /data/fonts ]; then
  find /data/fonts -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + || status=1
fi
if [ "$status" -eq 0 ]; then
  echo "GMS font processing completed."
else
  echo "GMS font processing completed with errors."
fi
exit "$status"
