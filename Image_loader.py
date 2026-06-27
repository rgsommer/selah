import os
from pathlib import Path
from PIL import Image
from modules.email_handler import log_error

def get_images_and_videos(config):
    try:
        portrait_files = []
        landscape_files = []

        def is_portrait(file_path):
            """Determine if an image is portrait based on dimensions."""
            try:
                with Image.open(file_path) as img:
                    width, height = img.size
                    return height > width
            except:
                return False

        def collect_files(folder, file_list, orientation=None):
            for path in Path(folder).rglob("*"):
                if path.suffix.lower() in config["valid_extensions"]:
                    if orientation:
                        # For portrait/landscape folders, use specified orientation
                        file_list.append(str(path))
                    else:
                        # For display/art folders, detect orientation
                        if path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                            if is_portrait(path):
                                portrait_files.append(str(path))
                            else:
                                landscape_files.append(str(path))
                        else:
                            # Videos assumed to fit both orientations
                            portrait_files.append(str(path))
                            landscape_files.append(str(path))

        if config["media_mode"] == "separate":
            # Collect from specific folders
            collect_files(config["portrait_dir"], portrait_files, orientation="portrait")
            collect_files(config["landscape_dir"], landscape_files, orientation="landscape")
            collect_files(config["art_dir"], [], orientation=None)  # Art uses orientation detection
            collect_files(config["display_dir"], [], orientation=None)  # Display uses orientation detection
            # Collect dated folders (e.g., media/YYYY-MM-DD/)
            for path in Path(config["media_folder"]).glob("????-??-??"):
                if path.is_dir():
                    collect_files(path, [], orientation=None)
        else:
            # Collect all media with orientation detection
            collect_files(config["media_folder"], [], orientation=None)

        return portrait_files, landscape_files
    except Exception as e:
        log_error(f"Image loading failed: {e}", critical=True, config=config)
        return [], []