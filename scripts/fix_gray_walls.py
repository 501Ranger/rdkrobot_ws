import cv2
import shutil

map_path = 'maps/my_map.pgm'
backup_path = 'maps/my_map_backup.pgm'

# Backup original map
shutil.copy(map_path, backup_path)

# Read the image in grayscale
img = cv2.imread(map_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"Error reading image: {map_path}")
    exit(1)

# In ROS maps:
# 254/255 = free space (white)
# 205 = unknown (light gray)
# 0 = obstacle (black)
# 
# Due to rotation, some walls might have become dark gray (e.g., 50-150).
# We will set any pixel darker than 200 to 0 (pure black).
# And we can leave >= 200 as they are, so we don't mess up the unknown/free spaces.

# Apply thresholding
# Anything < 200 becomes 0, anything >= 200 remains unchanged.
# Create a mask for pixels < 200
mask = img < 200

# Set those pixels to 0
img[mask] = 0

# Save the processed image
cv2.imwrite(map_path, img)

print(f"Successfully processed {map_path}. Backup saved to {backup_path}.")
