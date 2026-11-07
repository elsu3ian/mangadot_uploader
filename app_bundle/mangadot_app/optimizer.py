"""CBZ Optimizer backend."""
import os
import tempfile
import zipfile
import shutil
import sys
import subprocess
import platform
import logging
from pathlib import Path
import io

class OptimizerError(Exception):
    pass

OPTIMIZE_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
_PILLOW_MODULE = None
_MOZJPEG_MODULE = None
_MOZJPEG_AVAILABLE = None
_PINGO_BINARY_CACHE = None

def _pingo_binary_name():
    return "pingo.exe" if platform.system() == "Windows" else "pingo"

def _find_pingo_binary():
    global _PINGO_BINARY_CACHE
    if _PINGO_BINARY_CACHE is not None:
        return _PINGO_BINARY_CACHE or None

    # Look next to the main execution script
    script_dir = Path(sys.argv[0]).resolve().parent
    candidate = script_dir / _pingo_binary_name()
    if candidate.is_file():
        _PINGO_BINARY_CACHE = str(candidate)
        return _PINGO_BINARY_CACHE
    elif getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_cand = Path(sys._MEIPASS) / _pingo_binary_name()
        if meipass_cand.is_file():
            _PINGO_BINARY_CACHE = str(meipass_cand)
            return _PINGO_BINARY_CACHE
    _PINGO_BINARY_CACHE = ""
    return None

def _pingo_supported_here():
    return platform.system() in ("Windows", "Linux")

def ensure_pingo_ready():
    """Returns (path, warning_msg). Path is None if pingo can't be used."""
    if not _pingo_supported_here():
        return None, f"pingo has no official build for {platform.system()}. Falling back to built-in mozjpeg/Pillow."
    
    path = _find_pingo_binary()
    if path is None:
        return None, f"'{_pingo_binary_name()}' wasn't found next to the script. Falling back to built-in mozjpeg/Pillow."
    
    return path, None

def ensure_optimizer_deps(require_mozjpeg=False):
    global _PILLOW_MODULE, _MOZJPEG_MODULE, _MOZJPEG_AVAILABLE

    if _PILLOW_MODULE is None:
        try:
            from PIL import Image
            _PILLOW_MODULE = Image
        except ImportError:
            raise OptimizerError("Pillow is not installed. Please install it via CLI or 'pip install Pillow'.")

    if _MOZJPEG_AVAILABLE is None:
        try:
            import mozjpeg_lossless_optimization as mz
            _MOZJPEG_MODULE = mz
            _MOZJPEG_AVAILABLE = True
        except ImportError:
            _MOZJPEG_AVAILABLE = False

    if require_mozjpeg and not _MOZJPEG_AVAILABLE:
        raise OptimizerError("mozjpeg-lossless-optimization is not installed. Required for lossless JPEG compression.")

    return _PILLOW_MODULE, _MOZJPEG_MODULE

def _optimize_image_bytes(Image, mozjpeg, name, data, lossy, jpeg_quality, png_level, webp_quality):
    ext = os.path.splitext(name)[1].lower()

    try:
        if ext in ('.jpg', '.jpeg'):
            if not lossy:
                new_bytes = mozjpeg.optimize(data)
            else:
                with Image.open(io.BytesIO(data)) as im:
                    im.load()
                    if im.mode not in ('RGB', 'L'):
                        im = im.convert('RGB')
                    out = io.BytesIO()
                    im.save(out, format='JPEG', quality=jpeg_quality, optimize=True, progressive=True)
                    new_bytes = out.getvalue()
        elif ext == '.png':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                out = io.BytesIO()
                im.save(out, format='PNG', optimize=True, compress_level=png_level)
                new_bytes = out.getvalue()
        elif ext == '.webp':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                out = io.BytesIO()
                if not lossy:
                    im.save(out, format='WEBP', lossless=True, method=6, quality=100)
                else:
                    im.save(out, format='WEBP', quality=webp_quality, method=6)
                new_bytes = out.getvalue()
        elif ext == '.bmp':
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                if im.mode not in ('RGB', 'RGBA', 'L'):
                    im = im.convert('RGB')
                out = io.BytesIO()
                im.save(out, format='PNG', optimize=True, compress_level=png_level)
                new_bytes = out.getvalue()
        else:
            return data, False
    except Exception:
        logging.debug("optimizer: failed to optimize %r, leaving unchanged", name, exc_info=True)
        return data, False

    if len(new_bytes) < len(data):
        return new_bytes, True
    return data, False

def _resolve_optimized_output_path(input_path, replace):
    if replace:
        return input_path
    out_dir = input_path.parent / "optimized"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / input_path.name


def _finalize_optimized_cbz(input_path, new_entries, original_size, replace):
    """Shared tail of optimize_cbz()/optimize_cbz_pingo(): writes
    new_entries (name -> bytes) to a temp .cbz next to input_path,
    discards it if it didn't actually come out smaller than the
    original, otherwise replaces the original or moves it into the
    'optimized' subfolder. Returns the standard per-file result dict
    either way."""
    tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix='.cbz', dir=str(input_path.parent))
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
            for name, data in new_entries.items():
                zout.writestr(name, data)

        optimized_size = os.path.getsize(tmp_zip_path)
        if optimized_size >= original_size:
            os.remove(tmp_zip_path)
            return {"filename": input_path.name, "skipped": True, "original_size": original_size, "optimized_size": original_size}

        output_path = _resolve_optimized_output_path(input_path, replace)
        os.replace(tmp_zip_path, output_path)
    except Exception as e:
        if os.path.exists(tmp_zip_path):
            os.remove(tmp_zip_path)
        return {"filename": input_path.name, "error": str(e)}

    return {
        "filename": input_path.name,
        "output_name": str(output_path.relative_to(input_path.parent)) if not replace else output_path.name,
        "original_size": original_size,
        "optimized_size": optimized_size,
    }

def optimize_cbz(filepath, lossy=False, jpeg_quality=85, png_level=9, webp_quality=85, replace=False):
    Image, mozjpeg = ensure_optimizer_deps(require_mozjpeg=not lossy)
    input_path = Path(filepath)

    try:
        with zipfile.ZipFile(input_path, 'r') as zin:
            entries = zin.infolist()
            originals = {info.filename: zin.read(info.filename) for info in entries}
    except (zipfile.BadZipFile, OSError) as e:
        return {"filename": input_path.name, "error": str(e)}

    original_size = input_path.stat().st_size
    new_entries = {}
    changed_any = False

    for name, data in originals.items():
        if name.endswith('/'):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in OPTIMIZE_IMAGE_EXTS:
            new_data, changed = _optimize_image_bytes(Image, mozjpeg, name, data, lossy, jpeg_quality, png_level, webp_quality)
            out_name = os.path.splitext(name)[0] + '.png' if changed and ext == '.bmp' else name
            new_entries[out_name] = new_data
            changed_any = changed_any or changed
        else:
            new_entries[name] = data

    if not changed_any:
        return {"filename": input_path.name, "skipped": True, "original_size": original_size, "optimized_size": original_size}

    return _finalize_optimized_cbz(input_path, new_entries, original_size, replace)

def optimize_cbz_pingo(filepath, pingo_path, replace=False, lossy=False, jpeg_quality=85, webp_quality=85):
    input_path = Path(filepath)

    try:
        with zipfile.ZipFile(input_path, 'r') as zin:
            entries = zin.infolist()
            originals = {info.filename: zin.read(info.filename) for info in entries}
    except (zipfile.BadZipFile, OSError) as e:
        return {"filename": input_path.name, "error": str(e)}

    original_size = input_path.stat().st_size

    with tempfile.TemporaryDirectory(prefix="mangadot_pingo_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        image_files = []
        for name, data in originals.items():
            if name.endswith('/'): continue
            dest = tmp_dir_path / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if os.path.splitext(name)[1].lower() in OPTIMIZE_IMAGE_EXTS:
                image_files.append(dest)

        if not image_files:
            return {"filename": input_path.name, "skipped": True, "original_size": original_size, "optimized_size": original_size}

        cmd = [pingo_path]
        if lossy:
            cmd += [f"-jpeg={100 - jpeg_quality}", f"-webp={100 - webp_quality}"]
        else:
            cmd += ["-s8", "-lossless"]
        cmd += [str(p) for p in image_files]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"filename": input_path.name, "error": f"pingo failed to run: {e}"}

        new_entries = {}
        changed_any = False
        for name, data in originals.items():
            if name.endswith('/'): continue
            path_on_disk = tmp_dir_path / name
            try:
                new_data = path_on_disk.read_bytes()
            except OSError:
                new_data = data
            new_entries[name] = new_data
            if new_data != data:
                changed_any = True

        if not changed_any:
            return {"filename": input_path.name, "skipped": True, "original_size": original_size, "optimized_size": original_size}

        return _finalize_optimized_cbz(input_path, new_entries, original_size, replace)

def handle_chained_unoptimized_files(directory, results, replace):
    """Copies skipped/errored files to the optimized folder in chained mode."""
    output_dir = directory
    if not replace:
        output_dir = os.path.join(directory, "optimized")
        os.makedirs(output_dir, exist_ok=True)
        for r in results:
            if r.get("skipped") or r.get("error"):
                src = os.path.join(directory, r["filename"])
                dst = os.path.join(output_dir, r["filename"])
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    pass
    return output_dir