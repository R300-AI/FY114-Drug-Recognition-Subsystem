with open("/home/ubuntu/hemo-detection-service/data/test.txt", "r") as f:
    data = f.read()
    print(data)

with open("/home/ubuntu/hemo-detection-service/data/output.txt", "w") as f:
    f.write(f"{data} is a test output.")