from eminent.sensors.vision2p5d import VideoCapture 
import cv2

# Default ELAN Hardware Ids (VID/PID). Modify if your Device Manager shows different values.
cap = VideoCapture(vid=0x04F3, pid=0x0C7E)
    
while True:
    ret, frame = cap.read()
    if ret:
        cv2.imshow("MN96100C Frame", cv2.resize(frame, (640, 640)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    else:
        print("Failed to read frame")
        break

cap.release()
cv2.destroyAllWindows()