import time
import math
from collections import defaultdict
from app.models.event import Event
from sqlalchemy.orm import Session
from app.db.database import engine
from uuid import uuid4
from datetime import datetime
import cv2
import os


class EventEngine:
    def __init__(self,loiter_radius=30,loiter_time=15):
        self.loiter_radius = loiter_radius
        self.loiter_time = loiter_time
        self.loittering_flag = {}
        self.bag_links = {}
        self.unattended_flags = {}
        self.bag_timer = {}
        self.zone_history = defaultdict(list)
        self.surge_flag = {}

    def save_snapshot(self, frame, event_id):
        os.makedirs("snapshots", exist_ok=True)
        path = f"snapshots/{event_id}.jpg"
        cv2.imwrite(path, frame)
        return path

    def get_zone(self, x, y, frame_width, frame_height):
        zone_w = frame_width // 3
        zone_h = frame_height // 3

        zone_x = max(0, min(int(x // zone_w), 2))
        zone_y = max(0, min(int(y // zone_h), 2))

        return f"{zone_x},{zone_y}"

    def detect_loiter(self,tracks,frame_width, frame_height, frame):
        current_time = time.time()
        for pid,data in tracks.items():
            if data['label']!='person':
                continue

            position = list(data['position'])
            if len(position)<30:
                continue

            cx = sum(p[0] for p in position) / len(position)
            cy = sum(p[1] for p in position) / len(position)

            max_dist = max_dist = max(
                                        math.sqrt((p[0]-cx)**2 + (p[1]-cy)**2)
                                        for p in position
                                    )

            time_diff = current_time - data['first_seen']

            if max_dist<self.loiter_radius and time_diff>self.loiter_time:
                if pid not in self.loittering_flag:
                    self.loittering_flag[pid]=True
                    print(f"[{time.strftime('%H:%M:%S')}] LOITERING detected person {pid}")
                    x, y = data['position'][-1]
                    zone = self.get_zone(x, y, frame_width, frame_height)
                    time_score = min(1.0, time_diff / (self.loiter_time * 2))
                    movement_score = 1 - min(1.0, max_dist / self.loiter_radius)

                    confidence = round((0.7 * time_score + 0.3 * movement_score), 2)
                    event_id = str(uuid4())
                    image_path = self.save_snapshot(frame, event_id)

                    with Session(engine) as session:
                        event = Event(
                            id = event_id,
                            timestamp = datetime.utcnow(),
                            event_type = 'loittering',
                            pid = pid,
                            zone = zone,
                            confidence = confidence,
                            image_path = image_path
                        )
                        session.add(event)
                        session.commit()
                        session.refresh(event)


    def detect_unattempted(self,tracked,frame_width, frame_height,frame):
        current_time = time.time()

        person = {pid:data for pid,data in tracked.items() if data['label']=='person'}
        obj = {pid:data for pid,data in tracked.items() if data['label'] in ['backpack','handbag', 'suitcase', 'bottle', 'knife', 'cell phone']}

        for bid,data in obj.items():
            o_pos = data['position'][-1]
            min_dist = float('inf')
            near_person = None
            for pid,pdata in person.items():
                pos = pdata['position'][-1]
                distance = math.dist(pos,o_pos)
                if distance <min_dist:
                    min_dist = distance
                    near_person = pid
            
            if min_dist<100:
                self.bag_links[bid] = near_person
                self.bag_timer.pop(bid, None)

            else:
                if bid not in self.bag_timer:
                    self.bag_timer[bid] = current_time
                
                time_diff = current_time - self.bag_timer[bid]

                if time_diff>20:
                    if bid not in self.unattended_flags:
                        self.unattended_flags[bid] = True
                        print(f"[{time.strftime('%H:%M:%S')}] UNATTENDED BAG detected id {bid}")
                        x, y = data['position'][-1]
                        zone = self.get_zone(x, y, frame_width, frame_height)
                        time_score = min(1.0, time_diff / 40)  # 40 sec = full confidence
                        distance_score = min(1.0, min_dist / 200)
                        confidence = round((0.6 * time_score + 0.4 * distance_score), 2)
                        event_id = str(uuid4())
                        image_path = self.save_snapshot(frame, event_id)
                        with Session(engine) as session:
                            event = Event(
                                id = event_id,
                                timestamp = datetime.utcnow(),
                                event_type = 'unattended object',
                                pid = near_person,
                                bid = bid,
                                zone = zone,
                                confidence = confidence,
                                image_path = image_path
                            )
                            session.add(event)
                            session.commit()
                            session.refresh(event)



    def detect_crowd_surge(self, tracks, frame_width, frame_height,frame):
        zone_count = {}

        for i in range(3):
            for j in range(3):
                zone_count[(i,j)]=0
        
        zone_w = frame_width // 3
        zone_h = frame_height // 3

        for pid,data in tracks.items():
            if data['label']!='person':
                continue
            x,y = data['position'][-1]
          
            zone_x = max(0, min(int(x // zone_w), 2))
            zone_y = max(0, min(int(y // zone_h), 2))
            zone_count[(zone_x,zone_y)]+=1

        current_time = time.time()

        for zone,count in zone_count.items():
            self.zone_history[zone].append((current_time,count))

            self.zone_history[zone]=[
                (t,c) for (t,c) in self.zone_history[zone]
                if current_time-t<20
            ]

            if len(self.zone_history[zone])>5:
                before = self.zone_history[zone][0][1]
                after = count
                if before > 0 and after>before*2:
                    if zone not in self.surge_flag:
                        self.surge_flag[zone] = True
                        print(f"[{time.strftime('%H:%M:%S')}] CROWD SURGE zone {zone}")
                        growth_ratio = after / max(1, before)
                        ratio_score = min(1.0, (growth_ratio - 1))  
                        size_score = min(1.0, after / 10)  
                        confidence = round((0.6 * ratio_score + 0.4 * size_score), 2)
                        event_id = str(uuid4())
                        image_path = self.save_snapshot(frame, event_id)
                        with Session(engine) as session:
                            
                            event = Event(
                                id=event_id,
                                timestamp=datetime.utcnow(),   
                                event_type='crowd surge',
                                zone=f"{zone[0]},{zone[1]}",
                                confidence = confidence,
                                image_path = image_path 
                            )
                            
                            session.add(event)
                            session.commit()
                            session.refresh(event)      
                    
    






