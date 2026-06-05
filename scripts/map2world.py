import cv2
import yaml
import os
import numpy as np

yaml_path = 'maps/my_map.yaml'
world_path = 'src/rdk_robot_bringup/worlds/hallway.world'

# Ensure output dir exists
os.makedirs(os.path.dirname(world_path), exist_ok=True)

with open(yaml_path, 'r') as f:
    map_info = yaml.safe_load(f)

img_path = os.path.join(os.path.dirname(yaml_path), map_info['image'])
res = map_info['resolution']
origin = map_info['origin'] # [x, y, yaw]
thresh = map_info.get('occupied_thresh', 0.65)

# Read image
img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"Error reading image: {img_path}")
    exit(1)

# PGM: 0 is black (obstacle), 255 is white (free). 
# val < 255 * (1 - thresh) is occupied.
occupancy_val = 255 * (1.0 - thresh)
_, thresh_img = cv2.threshold(img, int(occupancy_val), 255, cv2.THRESH_BINARY_INV)

# 膨胀处理：将墙壁变粗，连接断裂的部分（由于雷达扫描不完整或存在灰色过渡像素导致）
kernel = np.ones((5, 5), np.uint8)
thresh_img = cv2.dilate(thresh_img, kernel, iterations=1)

# 闭运算：进一步填补墙壁内部的细小空洞
thresh_img = cv2.morphologyEx(thresh_img, cv2.MORPH_CLOSE, kernel)

h, w = thresh_img.shape
visited = np.zeros((h, w), dtype=bool)

rects = []
# Greedy Meshing
for y in range(h):
    for x in range(w):
        if thresh_img[y, x] > 0 and not visited[y, x]:
            # find max width
            cw = 1
            while x + cw < w and thresh_img[y, x + cw] > 0 and not visited[y, x + cw]:
                cw += 1
            
            # find max height for this width
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

walls = []
for (x, y, cw, ch) in rects:
    # center of rectangle in image
    cx_img = x + cw / 2.0
    cy_img = y + ch / 2.0
    
    # map coordinates
    wx = origin[0] + cx_img * res
    wy = origin[1] + (h - cy_img) * res
    
    # physical sizes
    size_x = cw * res
    size_y = ch * res
    
    walls.append({
        'x': wx, 'y': wy, 'sx': size_x, 'sy': size_y
    })

world_header = """<?xml version="1.0" ?>
<sdf version="1.6">
  <world name="default">
    <include>
      <uri>model://ground_plane</uri>
    </include>
    <include>
      <uri>model://sun</uri>
    </include>
"""

world_footer = """
  </world>
</sdf>
"""

with open(world_path, 'w') as f:
    f.write(world_header)
    for i, w_dict in enumerate(walls):
        wall_sdf = f"""
    <model name='wall_{i}'>
      <static>1</static>
      <pose>{w_dict['x']} {w_dict['y']} 0.5 0 0 0</pose>
      <link name='link'>
        <collision name='collision'>
          <geometry>
            <box>
              <size>{w_dict['sx']} {w_dict['sy']} 1.0</size>
            </box>
          </geometry>
        </collision>
        <visual name='visual'>
          <geometry>
            <box>
              <size>{w_dict['sx']} {w_dict['sy']} 1.0</size>
            </box>
          </geometry>
          <material>
            <script>
              <uri>file://media/materials/scripts/gazebo.material</uri>
              <name>Gazebo/Grey</name>
            </script>
          </material>
        </visual>
      </link>
    </model>
"""
        f.write(wall_sdf)
    f.write(world_footer)

print(f"Generated {world_path} with {len(walls)} solid block walls.")
