import base64
import json
import uuid
import time
import gzip
from Crypto.PublicKey import RSA
from Crypto.Util.number import bytes_to_long, long_to_bytes

class XXTEA:
    DELTA = 0x9E3779B9

    @staticmethod
    def _to_int_array(data, include_len):
        length = len(data)
        n = (length + 3) >> 2
        arr = [0] * (n + 1 if include_len else n)
        if include_len:
            arr[n] = length
        for i in range(length):
            arr[i >> 2] |= (data[i] & 0xFF) << ((i & 3) << 3)
        return arr

    @staticmethod
    def _to_byte_array(data, include_len):
        n = len(data) << 2
        if include_len:
            m = data[-1]
            if m > n:
                return None
            n = m
        res = bytearray(n)
        for i in range(n):
            res[i] = (data[i >> 2] >> ((i & 3) << 3)) & 0xFF
        return res

    @classmethod
    def encrypt(cls, data, key):
        if not data:
            return data
        v = cls._to_int_array(data, True)
        k = cls._to_int_array(key, False)
        if len(k) < 4:
            k.extend([0] * (4 - len(k)))
        n = len(v) - 1
        z = v[n]
        y = v[0]
        q = 6 + 52 // (n + 1)
        sum_val = 0
        while q > 0:
            sum_val = (sum_val + cls.DELTA) & 0xFFFFFFFF
            e = (sum_val >> 2) & 3
            for p in range(n):
                y = v[p + 1]
                mx = (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ ((sum_val ^ y) + (k[(p & 3) ^ e] ^ z))) & 0xFFFFFFFF
                v[p] = (v[p] + mx) & 0xFFFFFFFF
                z = v[p]
            y = v[0]
            mx = (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ ((sum_val ^ y) + (k[(n & 3) ^ e] ^ z))) & 0xFFFFFFFF
            v[n] = (v[n] + mx) & 0xFFFFFFFF
            z = v[n]
            q -= 1
        return cls._to_byte_array(v, False)

    @classmethod
    def decrypt(cls, data, key):
        if not data:
            return data
        v = cls._to_int_array(data, False)
        k = cls._to_int_array(key, False)
        if len(k) < 4:
            k.extend([0] * (4 - len(k)))
        n = len(v) - 1
        if n < 1:
            return data
        z, y = v[n], v[0]
        q = 6 + 52 // (n + 1)
        sum_val = (q * cls.DELTA) & 0xFFFFFFFF
        while sum_val != 0:
            e = (sum_val >> 2) & 3
            for p in range(n, 0, -1):
                z = v[p-1]
                mx = (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ ((sum_val ^ y) + (k[(p & 3) ^ e] ^ z))) & 0xFFFFFFFF
                v[p] = (v[p] - mx) & 0xFFFFFFFF
                y = v[p]
            z = v[n]
            mx = (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ ((sum_val ^ y) + (k[(0 & 3) ^ e] ^ z))) & 0xFFFFFFFF
            v[0] = (v[0] - mx) & 0xFFFFFFFF
            y = v[0]
            sum_val = (sum_val - cls.DELTA) & 0xFFFFFFFF
        return cls._to_byte_array(v, True)

def get_user_key_from_encode_res(encode_res_b64, public_key_b64):
    """
    通过 RSA 公钥从 encode_res 中解密出 userKey (XXTEA 密钥)
    """
    try:
        key = RSA.importKey(base64.b64decode(public_key_b64))
        n, e = key.n, key.e
        c = bytes_to_long(base64.b64decode(encode_res_b64))
        m = pow(c, e, n)
        db = long_to_bytes(m)
        
        # 兼容不同版本的定位逻辑
        json_start = db.find(b'{')
        if json_start == -1:
            return None
        json_str = db[json_start:].decode('utf-8')
        return json.loads(json_str).get("userKey")
    except Exception:
        return None

def generate_traceparent():
    """
    生成 traceparent 请求头
    """
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    return f"00-{trace_id}-{span_id}-01"

def generate_encodeparam(crand, user_key, user_id):
    """
    生成 encodeparam 参数
    """
    timestamp = int(crand)
    random_uuid = uuid.uuid4().hex
    nonce = f"{user_id}:{random_uuid}:{timestamp}"
    security_params = {
        "timestamp": timestamp,
        "nonce": nonce
    }
    json_str = json.dumps(security_params, separators=(',', ':'))
    data_to_encrypt = json_str.encode('utf-8')
    key_bytes = user_key.encode('utf-8')
    encrypted_data = XXTEA.encrypt(data_to_encrypt, key_bytes)
    return base64.b64encode(encrypted_data).decode('utf-8')

def get_full_request_params(public_key_b64, user_id, encode_res_b64):
    """
    整合获取全套请求参数
    """
    user_key = get_user_key_from_encode_res(encode_res_b64, public_key_b64)
    if not user_key:
        return None
    crand = str(int(time.time() * 1000))
    encode_param = generate_encodeparam(crand, user_key, user_id)
    trace_parent = generate_traceparent()
    return {
        "crand": crand,
        "encodeparam": encode_param,
        "traceparent": trace_parent
    }

def decrypt_data(data, uk):
    """
    使用 userKey 解密 XXTEA 数据
    """
    try:
        try:
            b = base64.b64decode(data, validate=True)
        except Exception:
            b = data
        db = XXTEA.decrypt(b, uk.encode('utf-8'))
        if not db:
            return None
        try:
            return gzip.decompress(db).decode('utf-8', errors='ignore')
        except Exception:
            return db
    except Exception:
        return None

def decrypt_game_data(public_key_b64, res_b64, data):
    """
    完整流程解密游戏返回数据
    """
    uk = get_user_key_from_encode_res(res_b64, public_key_b64)
    if not uk:
        raise ValueError("Invalid encode_res or public_key")
    res = decrypt_data(data, uk)
    if not res:
        raise ValueError("Decryption failed")
    try:
        if isinstance(res, bytes):
            res = res.decode('utf-8')
        return json.loads(res)
    except Exception as e:
        raise ValueError(f"JSON error: {e}")

if __name__ == "__main__":
    pass
