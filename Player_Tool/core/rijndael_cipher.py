import copy
# 解密算法参考 AES（高级加密标准）的公开定义实现。
shifts = [
	[[0, 0], [1, 3], [2, 2], [3, 1]],
	[[0, 0], [1, 5], [2, 4], [3, 3]],
	[[0, 0], [1, 7], [3, 5], [4, 4]]
]
num_rounds = {
# [密钥大小][分组大小]
	16: {16: 10, 24: 12, 32: 14},
	24: {16: 12, 24: 12, 32: 14},
	32: {16: 14, 24: 14, 32: 14}
}
A = [
	[1, 1, 1, 1, 1, 0, 0, 0],
	[0, 1, 1, 1, 1, 1, 0, 0],
	[0, 0, 1, 1, 1, 1, 1, 0],
	[0, 0, 0, 1, 1, 1, 1, 1],
	[1, 0, 0, 0, 1, 1, 1, 1],
	[1, 1, 0, 0, 0, 1, 1, 1],
	[1, 1, 1, 0, 0, 0, 1, 1],
	[1, 1, 1, 1, 0, 0, 0, 1]
]
# 生成 log 与 a_log 表，用于在
# GF(2^m) 有限域中进行乘法运算（生成元 = 3）
a_log = [1]
for i in range(255):
	j = (a_log[-1] << 1) ^ a_log[-1]
	if j & 0x100 != 0:
		j ^= 0x11B
	a_log.append(j)

log = [0] * 256
for i in range(1, 255):
	log[a_log[i]] = i

# 在 GF(2^m) 有限域中执行乘法
def mul(a, b):
	if a == 0 or b == 0:
		return 0
	return a_log[(log[a & 0xFF] + log[b & 0xFF]) % 255]

# 根据 F^{-1}(x) 构造替换盒
box = [[0] * 8 for i in range(256)]
box[1][7] = 1
for i in range(2, 256):
	j = a_log[255 - log[i]]
	for t in range(8):
		box[i][t] = (j >> (7 - t)) & 0x01

B = [0, 1, 1, 0, 0, 0, 1, 1]

# 仿射变换：box[i] <- B + A*box[i]
cox = [[0] * 8 for i in range(256)]
for i in range(256):
	for t in range(8):
		cox[i][t] = B[t]
		for j in range(8):
			cox[i][t] ^= A[t][j] * box[i][j]

# S 盒与逆 S 盒
S = [0] * 256
Si = [0] * 256
for i in range(256):
	S[i] = cox[i][0] << 7
	for t in range(1, 8):
		S[i] ^= cox[i][t] << (7-t)
	Si[S[i] & 0xFF] = i

# T 盒
G = [
	[2, 1, 1, 3],
	[3, 2, 1, 1],
	[1, 3, 2, 1],
	[1, 1, 3, 2]
]

AA = [[0] * 8 for i in range(4)]

for i in range(4):
	for j in range(4):
		AA[i][j] = G[i][j]
		AA[i][i+4] = 1

for i in range(4):
	pivot = AA[i][i]
	for j in range(8):
		if AA[i][j] != 0:
			AA[i][j] = a_log[(255 + log[AA[i][j] & 0xFF] - log[pivot & 0xFF]) % 255]
	for t in range(4):
		if i != t:
			for j in range(i+1, 8):
				AA[t][j] ^= mul(AA[i][j], AA[t][i])
			AA[t][i] = 0

iG = [[0] * 4 for i in range(4)]

for i in range(4):
	for j in range(4):
		iG[i][j] = AA[i][j + 4]

def mul4(a, bs):
	if a == 0:
		return 0
	rr = 0
	for b in bs:
		rr <<= 8
		if b != 0:
			rr = rr | mul(a, b)
	return rr

T1 = []
T2 = []
T3 = []
T4 = []
T5 = []
T6 = []
T7 = []
T8 = []
U1 = []
U2 = []
U3 = []
U4 = []

for t in range(256):
	s = S[t]
	T1.append(mul4(s, G[0]))
	T2.append(mul4(s, G[1]))
	T3.append(mul4(s, G[2]))
	T4.append(mul4(s, G[3]))

	s = Si[t]
	T5.append(mul4(s, iG[0]))
	T6.append(mul4(s, iG[1]))
	T7.append(mul4(s, iG[2]))
	T8.append(mul4(s, iG[3]))

	U1.append(mul4(t, iG[0]))
	U2.append(mul4(t, iG[1]))
	U3.append(mul4(t, iG[2]))
	U4.append(mul4(t, iG[3]))

# 轮常量
r_con = [1]
r = 1
for t in range(1, 30):
	r = mul(2, r)
	r_con.append(r)

class RijndaelCBC:
# 这里只实现 CBC 模式，其余模式当前不需要
	def __init__(self, key, block_size):
		if len(key) not in (16, 24, 32):
			raise ValueError('Invalid key size: %s' % str(len(key)))
		if block_size not in (16, 24, 32):
			raise ValueError('Invalid block size: %s' % str(block_size))

		self.key = key
		self.block_size = block_size
		rounds = num_rounds[len(key)][block_size]
		b_c = block_size // 4
		# 加密轮密钥
		k_e = [[0] * b_c for _ in range(rounds + 1)]
		# 解密轮密钥
		k_d = [[0] * b_c for _ in range(rounds + 1)]
		roundkeyCount = (rounds + 1) * b_c
		k_c = len(key) // 4
		
		# 把用户密钥材料复制到临时整数数组
		tk = []
		for i in range(0, k_c):
			tk.append((ord(key[i * 4:i * 4 + 1]) << 24) | (ord(key[i * 4 + 1:i * 4 + 1 + 1]) << 16) |
					(ord(key[i * 4 + 2: i * 4 + 2 + 1]) << 8) | ord(key[i * 4 + 3:i * 4 + 3 + 1]))
		
		# 把数值复制到轮密钥数组
		t = 0
		j = 0
		while j < k_c and t < roundkeyCount:
			k_e[t // b_c][t % b_c] = tk[j]
			k_d[rounds - (t // b_c)][t % b_c] = tk[j]
			j += 1
			t += 1
		r_con_pointer = 0
		while t < roundkeyCount:
			# 使用 phi（轮密钥演化函数）继续推导轮密钥
			tt = tk[k_c - 1]
			tk[0] ^= (S[(tt >> 16) & 0xFF] & 0xFF) << 24 ^ \
					(S[(tt >> 8) & 0xFF] & 0xFF) << 16 ^ \
					(S[tt & 0xFF] & 0xFF) << 8 ^ \
					(S[(tt >> 24) & 0xFF] & 0xFF) ^ \
					(r_con[r_con_pointer] & 0xFF) << 24
			r_con_pointer += 1
			if k_c != 8:
				for i in range(1, k_c):
					tk[i] ^= tk[i - 1]
			else:
				for i in range(1, k_c // 2):
					tk[i] ^= tk[i - 1]
				tt = tk[k_c // 2 - 1]
				tk[k_c // 2] ^= (S[tt & 0xFF] & 0xFF) ^ \
								(S[(tt >> 8) & 0xFF] & 0xFF) << 8 ^ \
								(S[(tt >> 16) & 0xFF] & 0xFF) << 16 ^ \
								(S[(tt >> 24) & 0xFF] & 0xFF) << 24
				for i in range(k_c // 2 + 1, k_c):
					tk[i] ^= tk[i - 1]
			# 把数值复制到轮密钥数组
			j = 0
			while j < k_c and t < roundkeyCount:
				k_e[t // b_c][t % b_c] = tk[j]
				k_d[rounds - (t // b_c)][t % b_c] = tk[j]
				j += 1
				t += 1
		# 在需要的位置执行逆列混合
		for r in range(1, rounds):
			for j in range(b_c):
				tt = k_d[r][j]
				k_d[r][j] = (
					U1[(tt >> 24) & 0xFF] ^
					U2[(tt >> 16) & 0xFF] ^
					U3[(tt >> 8) & 0xFF] ^
					U4[tt & 0xFF]
				)
		self.Ke = k_e
		self.Kd = k_d
	def decrypt(self, cipher):
		assert len(cipher) % self.block_size == 0
		ppt = bytes()
		offset = 0
		v = self.key[4: 28]
		while offset < len(cipher):
			block = cipher[offset:offset + self.block_size]
			if len(block) != self.block_size:
				raise ValueError(
					'Wrong block length, expected %s got %s' % (
						str(self.block_size),
						str(len(block))
					)
				)

			k_d = self.Kd
			b_c = self.block_size // 4
			rounds = len(k_d) - 1
			if b_c == 4:
				s_c = 0
			elif b_c == 6:
				s_c = 1
			else:
				s_c = 2
			s1 = shifts[s_c][1][1]
			s2 = shifts[s_c][2][1]
			s3 = shifts[s_c][3][1]
			a = [0] * b_c
			# 临时工作数组
			t = [0] * b_c
			# 把密文转换为整数数组并加入轮密钥
			for i in range(b_c):
				t[i] = (ord(block[i * 4: i * 4 + 1]) << 24 |
						ord(block[i * 4 + 1: i * 4 + 1 + 1]) << 16 |
						ord(block[i * 4 + 2: i * 4 + 2 + 1]) << 8 |
						ord(block[i * 4 + 3: i * 4 + 3 + 1])) ^ k_d[0][i]
			# 执行各轮变换
			for r in range(1, rounds):
				for i in range(b_c):
					a[i] = (T5[(t[i] >> 24) & 0xFF] ^
							T6[(t[(i + s1) % b_c] >> 16) & 0xFF] ^
							T7[(t[(i + s2) % b_c] >> 8) & 0xFF] ^
							T8[t[(i + s3) % b_c] & 0xFF]) ^ k_d[r][i]
				t = copy.copy(a)
			# 最后一轮使用特殊处理
			result = []
			for i in range(b_c):
				tt = k_d[rounds][i]
				result.append((Si[(t[i] >> 24) & 0xFF] ^ (tt >> 24)) & 0xFF)
				result.append((Si[(t[(i + s1) % b_c] >> 16) & 0xFF] ^ (tt >> 16)) & 0xFF)
				result.append((Si[(t[(i + s2) % b_c] >> 8) & 0xFF] ^ (tt >> 8)) & 0xFF)
				result.append((Si[t[(i + s3) % b_c] & 0xFF] ^ tt) & 0xFF)
			decrypted = bytes()
			for xx in result:
				decrypted += bytes([xx])
			ppt += self.x_or_block(decrypted, v)
			offset += self.block_size
			v = block
		
		assert len(ppt) % self.block_size == 0
		offset = len(ppt)
		if offset == 0:
			return b''
		end = offset - self.block_size + 1

		while offset > end:
			offset -= 1
			if ppt[offset]:
				return ppt[:offset + 1]

		return ppt[:end]
	def encrypt(self, source: bytes):
		# 填充方式
		pad_size = self.block_size - ((len(source) + self.block_size - 1) % self.block_size + 1)
		ppt = source + b'\0' * pad_size
		offset = 0

		ct = bytes()
		v = self.key[4: 28]
		while offset < len(ppt):
			block = ppt[offset:offset + self.block_size]
			block = self.x_or_block(block, v)
			# 加密一组数据，每组大小为 block_size
			if len(block) != self.block_size:
				raise ValueError(
					'Wrong block length, expected %s got %s' % (
						str(self.block_size),
						str(len(block))
					)
				)

			k_e = self.Ke

			b_c = self.block_size // 4
			rounds = len(k_e) - 1
			if b_c == 4:
				s_c = 0
			elif b_c == 6:
				s_c = 1
			else:
				s_c = 2
			s1 = shifts[s_c][1][0]
			s2 = shifts[s_c][2][0]
			s3 = shifts[s_c][3][0]
			a = [0] * b_c
			# 临时工作数组
			t = []
			# 把源数据转换为整数数组并加入轮密钥
			for i in range(b_c):
				t.append((ord(block[i * 4: i * 4 + 1]) << 24 |
						ord(block[i * 4 + 1: i * 4 + 1 + 1]) << 16 |
						ord(block[i * 4 + 2: i * 4 + 2 + 1]) << 8 |
						ord(block[i * 4 + 3: i * 4 + 3 + 1])) ^ k_e[0][i])
			# 执行各轮变换
			for r in range(1, rounds):
				for i in range(b_c):
					a[i] = (T1[(t[i] >> 24) & 0xFF] ^
							T2[(t[(i + s1) % b_c] >> 16) & 0xFF] ^
							T3[(t[(i + s2) % b_c] >> 8) & 0xFF] ^
							T4[t[(i + s3) % b_c] & 0xFF]) ^ k_e[r][i]
				t = copy.copy(a)
			# 最后一轮使用特殊处理
			result = []
			for i in range(b_c):
				tt = k_e[rounds][i]
				result.append((S[(t[i] >> 24) & 0xFF] ^ (tt >> 24)) & 0xFF)
				result.append((S[(t[(i + s1) % b_c] >> 16) & 0xFF] ^ (tt >> 16)) & 0xFF)
				result.append((S[(t[(i + s2) % b_c] >> 8) & 0xFF] ^ (tt >> 8)) & 0xFF)
				result.append((S[t[(i + s3) % b_c] & 0xFF] ^ tt) & 0xFF)
			block = bytes()
			for xx in result:
				block += bytes([xx])
			ct += block
			offset += self.block_size
			v = block
		return ct
	def x_or_block(self, b1, b2):
		i = 0
		r = bytes()
		while i < self.block_size:
			r += bytes([ord(b1[i:i+1]) ^ ord(b2[i:i+1])])
			i += 1
		return r