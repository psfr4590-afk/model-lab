import os
root = r"C:\Users\krash\Desktop\Training Bullshit"
fpath = os.path.join(root, 'run_pipeline.py')
with open(fpath, 'rb') as f:
    data = f.read()
if data[0:1] == b'?':
    data = data[1:]
    with open(fpath, 'wb') as f:
        f.write(data)
    print('Stripped leading ?. First 16 bytes now:', data[:16])
else:
    print('No leading ? found. First byte:', hex(data[0]))
