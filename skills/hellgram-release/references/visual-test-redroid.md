# Visual/functional APK testing with Redroid (no KVM required)

Verified path for booting real Android in Docker on a KVM-less Linux host and driving the Hellgram APK through adb.

## Setup (once per host)
```bash
sudo apt-get install -y docker.io && sudo systemctl start docker
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
sudo mkdir -p /dev/binderfs && sudo mount -t binder binder /dev/binderfs   # /dev/binder* only appear after this mount
```
If `modprobe ashmem_linux` fails, that is fine — modern kernels have ashmem in-kernel; binderfs is what matters.

## Boot an instance
```bash
sudo docker run -itd --privileged --rm -v ~/redroid-data:/data -p 5555:5555 \
  --name hg-test redroid/redroid:14.0.0_64only-latest \
  androidboot.redroid_gpu_mode=guest   # software rendering, no GPU needed
adb connect localhost:5555
adb -s localhost:5555 shell getprop sys.boot_completed   # wait for '1'
```
The arm64-only release APK installs and runs on the `_64only` image despite the x86_64 host.

## Install, launch, verify
```bash
adb install -r <apk>
adb shell am start -n ua.entaytion.entinygram/org.telegram.ui.LaunchActivity
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png      # -> vision_analyze
adb shell uiautomator dump /sdcard/u.xml && adb shell cat /sdcard/u.xml  # -> parse text=/bounds= for taps
adb shell input tap X Y | input swipe ... | input text "..." | input keyevent KEYCODE_BACK
```
Screen is 720x1280 by default. Read element coordinates from the uiautomator XML `bounds="[l,t][r,b]"` and tap the center — blind coordinate taps on the wrong overlay (dialog over screen) silently do nothing.

## Flow-repro tips
- Cold-restart repro of hangs: `am force-stop` then `am start`, and time to first responsive UI by polling uiautomator dump each second (stops dumping during transitions — retry on `null root node`).
- Compare screenshots between steps with PIL `ImageChops.difference(...).getbbox()` to detect whether a tap changed anything (a frame-identical pair = the tap did nothing).
- Android keyboard: `adb shell input text` works regardless of the on-screen keypad; keypad taps are only needed for UI verification shots.
- Keep taps/looks paced with short sleeps; the container is slow under software rendering — give 5–15 s after each navigation before asserting.
