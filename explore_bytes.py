from pathlib import Path

def explore_bytes(file_path):
    path = Path(file_path)
    if not path.exists():
        return
    
    data = path.read_bytes()
    print(f"File size: {len(data)}")
    print(f"Top 100 bytes: {data[:100].hex(' ')}")
    
    # Try to find '삼성전자' in CP949
    # S-A-M-S-U-N-G-E-L-E-C-T-R-O-N-I-C-S in CP949: bb ec bc ba b1 e1 wk
    # Actually just look for some high-bit bytes
    print("\nByte ranges > 127:")
    for i in range(len(data)):
        if data[i] > 127:
            snippet = data[max(0, i-5):min(len(data), i+15)]
            print(f"At {i}: {snippet.hex(' ')}")
            try:
                print(f"  as CP949: {snippet.decode('cp949')}")
            except: pass
            break

explore_bytes(r"D:\py\report-us\report_volume.txt")
