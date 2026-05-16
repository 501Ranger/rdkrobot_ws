import cv2
import yaml
import numpy as np

yaml_path = 'maps/my_map.yaml'
with open(yaml_path, 'r') as f:
    map_info = yaml.safe_load(f)

img_path = 'maps/' + map_info['image']
img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
thresh = map_info.get('occupied_thresh', 0.65)
occupancy_val = 255 * (1.0 - thresh)
_, thresh_img = cv2.threshold(img, int(occupancy_val), 255, cv2.THRESH_BINARY_INV)

# morphological open to remove small holes in walls
# kernel = np.ones((3, 3), np.uint8)
# thresh_img = cv2.morphologyEx(thresh_img, cv2.MORPH_OPEN, kernel)
# thresh_img = cv2.morphologyEx(thresh_img, cv2.MORPH_CLOSE, kernel)

h, w = thresh_img.shape
visited = np.zeros((h, w), dtype=bool)

rects = []
for y in range(h):
    for x in range(w):
        if thresh_img[y, x] > 0 and not visited[y, x]:
            # find max width
            cw = 1
            while x + cw < w and thresh_img[y, x + cw] > 0 and not visited[y, x + cw]:
                cw += 1
            # find max height
            ch = 1
            valid_height = True
            while y + ch < h and valid_height:
                for cx in range(cw):
                    if thresh_img[y + ch, x + cx] == 0 or visited[y + ch, x + cx]:
                        valid_height = False
                        break
                if valid_height:
                    ch += 1
            
            # mark visited
            visited[y:y+ch, x:x+cw] = True
            rects.append((x, y, cw, ch))

print(f"Generated {len(rects)} rectangles.")
