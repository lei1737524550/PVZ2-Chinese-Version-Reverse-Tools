from struct import unpack, pack, error
from json import dumps, load

class RTONDecoder():
	def __init__(self, comma = b",", currrent_indent = b"\r\n", doublePoint = b": ", ensureAscii = False, indent = b"    ", repairFiles = True, sortKeys = False, sortValues = False, warning_message = lambda x: None):
		self.comma = comma
		self.currrent_indent = currrent_indent
		self.doublePoint = doublePoint
		self.ensureAscii = ensureAscii
		self.warning_message = warning_message
		self.indent = indent
		self.repairFiles = repairFiles
		self.sortKeys = sortKeys
		self.sortValues = sortValues

	def parse_number(self, fp):
		num = fp.read(1)[0]
		result = num & 0x7f
		i = 128
		while num > 127:
			num = fp.read(1)[0]
			result += i * (num & 0x7f)
			i *= 128
		return result
	def parse_text(self, fp):
	# 类型 81, 90
		byte = fp.read(self.parse_number(fp))
		try:
			return byte.decode()
		except Exception:
			return byte.decode('latin-1')
	def parse_utf8_text(self, fp):
		i1 = self.parse_number(fp) # 字符长度
		string = fp.read(self.parse_number(fp)).decode()
		i2 = len(string)
		if i1 != i2:
			self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": Unicode string of character length " + str(i2) + " found, expected " + str(i1))
		return string

	def parse_false(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 00
		return b"false"
	def parse_true(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 01
		return b"true"
	def parse_int8(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 08
		return repr(unpack("b", fp.read(1))[0]).encode()
	def parse_zero(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 09, 0b, 11, 13, 21, 27, 41, 47
		return b"0"
	def parse_uint8(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 0a
		return repr(fp.read(1)[0]).encode()
	def parse_int16(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 10
		return repr(unpack("<h", fp.read(2))[0]).encode()
	def parse_uint16(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 12
		return repr(unpack("<H", fp.read(2))[0]).encode()
	def parse_int32(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 20
		return repr(unpack("<i", fp.read(4))[0]).encode()
	def parse_float32(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 22
		return repr(unpack("<f", fp.read(4))[0]).replace("inf", "Infinity").replace("nan", "NaN").encode()
	def parse_zero_point_zero(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 23, 43
		return b"0.0"
	def parse_uvarint(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 24、28、44、48
		return repr(self.parse_number(fp)).encode()
	def parse_varint(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 25、29、45、49
		num = self.parse_number(fp)
		if num % 2:
			num = -num - 1
		return repr(num // 2).encode()
	def parse_uint32(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 26
		return repr(unpack("<I", fp.read(4))[0]).encode()
	def parse_int64(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 40
		return repr(unpack("<q", fp.read(8))[0]).encode()
	def parse_float64(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 42
		return repr(unpack("<d", fp.read(8))[0]).replace("inf", "Infinity").replace("nan", "NaN").encode()
	def parse_uint64(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 46
		return repr(unpack("<Q", fp.read(8))[0]).encode()
	def parse_str(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 81
		return dumps(self.parse_text(fp), ensure_ascii = self.ensureAscii).encode()
	def parse_printable_str(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 82
		return dumps(self.parse_utf8_text(fp), ensure_ascii = self.ensureAscii).encode()
	def parse_rtid(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 83
		return self.rtid_mappings[b"\x83" + fp.read(1)](self, fp)
	def parse_rtid_zero(self, fp):
	# 类型 8300
		return b'"RTID(0)"'
	def parse_rtid_uid(self, fp):
	# 类型 8302
		p1 = self.parse_utf8_text(fp)
		i2 = repr(self.parse_number(fp))
		i1 = repr(self.parse_number(fp))
		return dumps("RTID(" + i1 + "." + i2 + "." + fp.read(4)[::-1].hex() + "@" + p1 + ")", ensure_ascii = self.ensureAscii).encode()
	def parse_rtid_ref(self, fp):
	# 类型 8303
		p1 = self.parse_utf8_text(fp)
		return dumps("RTID(" + self.parse_utf8_text(fp) + "@" + p1 + ")", ensure_ascii = self.ensureAscii).encode()
	def parse_zero_ref(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 84
		return b'"RTID(0)"'
	def parse_root_object(self, fp):
	# 类型 85*
		VERSION = unpack("<I", fp.read(4))[0]
		return self.parse_object(fp, self.currrent_indent, [], [])
	def parse_object(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 85
		new_indent = currrent_indent + self.indent
		items = []
		try:
			code = fp.read(1)
			while code != b"\xff":
				key = self.key_mappings[code](self, fp, new_indent, cached_strings, cached_printable_strings)
				value = self.value_mappings[fp.read(1)](self, fp, new_indent, cached_strings, cached_printable_strings)
				items.append(key + self.doublePoint + value)
				code = fp.read(1)
		except KeyError as k:
			if str(k) == 'b""':
				if self.repairFiles:
					self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": end of file")
				else:
					raise EOFError
			else:
				raise TypeError("unknown tag " + k.args[0].hex())
		except (error, IndexError):
			if self.repairFiles:
				self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": end of file")
			else:
				raise EOFError
		i2 = len(items)
		if i2 != 0:
			if self.sortKeys:
				items = sorted(items)
			return b"{" + new_indent + (self.comma + new_indent).join(items) + currrent_indent + b"}"
		return b"{}"
	def parse_list(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 86
		self.list_mappings[b"\x86" + fp.read(1)]
		new_indent = currrent_indent + self.indent
		items = []
		i1 = self.parse_number(fp)
		try:
			code = fp.read(1)
			while code != b"\xfe":
				value = self.value_mappings[code](self, fp, new_indent, cached_strings, cached_printable_strings)
				items.append(value)
				code = fp.read(1)
		except KeyError as k:
			if str(k) == 'b""':
				if self.repairFiles:
					self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": end of file")
				else:
					raise EOFError
			else:
				raise TypeError("unknown tag " + k.args[0].hex())
		except (error, IndexError):
			if self.repairFiles:
				self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": end of file")
			else:
				raise EOFError
		i2 = len(items)
		if i1 != i2:
			self.warning_message("SilentError: " + fp.name + " pos " + str(fp.tell()) + ": Array of length " + str(i1) + " found, expected " + str(i2))
		if i2 != 0:
			if self.sortValues:
				items = sorted(sorted(items), key = lambda key : len(key))
			return b"[" + new_indent + (self.comma + new_indent).join(items) + currrent_indent + b"]"
		return b"[]"
	def parse_cached_str(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 90
		value = dumps(self.parse_text(fp), ensure_ascii = self.ensureAscii).encode()
		cached_strings.append(value)
		return value
	def parse_cached_str_recall(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 91
		return cached_strings[self.parse_number(fp)]
	def parse_cached_printable_str(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 92
		value = dumps(self.parse_utf8_text(fp), ensure_ascii = self.ensureAscii).encode()
		cached_printable_strings.append(value)
		return value
	def parse_cached_printable_str_recall(self, fp, currrent_indent, cached_strings, cached_printable_strings):
	# 类型 93
		return cached_printable_strings[self.parse_number(fp)]
	rtid_mappings = {
		b"\x83\0": parse_rtid_zero,
		b"\x83\x02": parse_rtid_uid,
		b"\x83\x03": parse_rtid_ref
	}
	key_mappings = {
		b"\x81": parse_str,
		b"\x82": parse_printable_str,
		b"\x83": parse_rtid,
		
		b"\x90": parse_cached_str,
		b"\x91": parse_cached_str_recall,
		b"\x92": parse_cached_printable_str,
		b"\x93": parse_cached_printable_str_recall
	}
	value_mappings = {
		b"\0": parse_false,
		b"\x01": parse_true,

		b"\x08": parse_int8,
		b"\t": parse_zero, # int8 零值
		b"\n": parse_uint8,
		b"\x0b": parse_zero, # uint8 零值

		b"\x10": parse_int16,
		b"\x11": parse_zero, # int16 零值
		b"\x12": parse_uint16,
		b"\x13": parse_zero, # uint16 零值

		b" ": parse_int32,
		b"!": parse_zero, # int32 零值
		b'"': parse_float32,
		b"#": parse_zero_point_zero, # float 零值
		b"$": parse_uvarint, # int32 无符号变长整数
		b"%": parse_varint, # int32 有符号变长整数
		b"&": parse_uint32,
		b"'": parse_zero, # uint32 零值
		b"(": parse_uvarint, # uint32 无符号变长整数

		b"@": parse_int64,
		b"A": parse_zero, # int64 零值
		b"B": parse_float64,
		b"C": parse_zero_point_zero, # double 零值
		b"D": parse_uvarint, # int64 无符号变长整数
		b"E": parse_varint, # int64 有符号变长整数
		b"F": parse_uint64,
		b"G": parse_zero, # uint64 零值
		b"H": parse_uvarint, # uint64 无符号变长整数

		b"\x81": parse_str,
		b"\x82": parse_printable_str,
		b"\x83": parse_rtid,
		b"\x84": parse_zero_ref,
		b"\x85": parse_object,
		b"\x86": parse_list,

		b"\x90": parse_cached_str,
		b"\x91": parse_cached_str_recall,
		b"\x92": parse_cached_printable_str,
		b"\x93": parse_cached_printable_str_recall,
	}
	list_mappings = {
		b"\x86\xfd": None
	}

class list2:
# 附加列表类型
	def __init__(self, data):
		self.data = data

class JSONDecoder():
	def __init__(self):
		self.Infinity = [float("Infinity"), float("-Infinity")] # 正无穷与负无穷值
	
	def encode_object_pairs(self, pairs):
	# 把对象转换为元组列表
		return list2(pairs)
	def encode_number(self, integ):
	# 变长数字
		integ, i = divmod(integ, 128)
		if (integ):
			i += 128
		string = pack("B", i)
		while integ:
			integ, i = divmod(integ, 128)
			if (integ):
				i += 128
			string += pack("B", i)
		return string
	def encode_utf8_text(self, string):
	# RTID 中的 Unicode 文本
		encoded_string = string.encode()
		return self.encode_number(len(string)) + self.encode_number(len(encoded_string)) + encoded_string

	def encode_bool(self, boolean):
	# 类型 00, 01
		if boolean:
			return b"\x01"
		else:
			return b"\x00"
	def encode_int(self, integ):
	# 类型 08, 0a, 10, 12, 20, 21, 25, 26, 29, 40, 45, 46, 49
		if integ == 0:
			return b"!"
		elif 0 <= integ <= 2097151:
			return b"$" + self.encode_number(integ)
		elif -1048576 <= integ <= 0:
			return b"%" + self.encode_number(-1 - 2 * integ)
		elif -2147483648 <= integ <= 2147483647:
			return b" " + pack("<i", integ)
		elif 0 <= integ < 4294967295:
			return b"&" + pack("<I", integ)
		elif 0 <= integ <= 562949953421311:
			return b"D" + self.encode_number(integ)
		elif -281474976710656 <= integ <= 0:
			return b"E" + self.encode_number(-1 - 2 * integ)
		elif -9223372036854775808 <= integ <= 9223372036854775807:
			return b"@" + pack("<q", integ)
		elif 0 <= integ <= 18446744073709551615:
			return b"F" + pack("<Q", integ)
		elif 0 <= integ:
			return b"D" + self.encode_number(integ)
		else:
			return b"E" + self.encode_number(-1 - 2 * integ)
	def encode_float(self, dec):
	# 类型 22, 42
		if dec == 0:
			return b"#"
		elif dec != dec or dec in self.Infinity or -340282346638528859811704183484516925440 <= dec <= 340282346638528859811704183484516925440 and dec == unpack("<f", pack("<f", dec))[0]:
			return b'"' + pack("<f", dec)
		else:
			return b"B" + pack("<d", dec)
	def encode_rtid(self, string):
	# 类型 83
		if "@" in string:
			name, type = string[5:-1].split("@")
			if name.count(".") == 2:
				i2, i1, i3 = name.split(".")
				return b"\x83\x02" + self.encode_utf8_text(type) + self.encode_number(int(i1)) + self.encode_number(int(i2)) + bytes.fromhex(i3)[::-1]
			else:
				return b"\x83\x03" + self.encode_utf8_text(type) + self.encode_utf8_text(name)
		else:
			return b"\x84"
	def encode_root_object(self, file):
	# 类型 85*
		cached_strings = {}
		items = []
		for key, value in load(file, object_pairs_hook = self.encode_object_pairs).data:
			key = self.encode_cached_string(key, cached_strings)
			if isinstance(value, str):
				if "RTID()" == value[:5] + value[-1:]:
					value = self.encode_rtid(value)
				else:
					value = self.encode_cached_string(value, cached_strings)
			elif isinstance(value, bool):
				value = self.encode_bool(value)
			elif isinstance(value, int):
				value = self.encode_int(value)
			elif isinstance(value, float):
				value = self.encode_float(value)
			elif isinstance(value, list):
				value = self.encode_array(value, cached_strings)
			elif isinstance(value, list2):
				value = self.encode_object(value, cached_strings)
			elif value == None:
				value = b"\x84"
			else:
				raise TypeError(type(value))
			items.append(key + value)
		return b"RTON\x01\0\0\0" + b"".join(items) + b"\xffDONE"
	def encode_object(self, data, cached_strings):
	# 类型 85
		items = []
		for key, value in data.data:
			key = self.encode_cached_string(key, cached_strings)
			if isinstance(value, str):
				if "RTID()" == value[:5] + value[-1:]:
					value = self.encode_rtid(value)
				else:
					value = self.encode_cached_string(value, cached_strings)
			elif isinstance(value, bool):
				value = self.encode_bool(value)
			elif isinstance(value, int):
				value = self.encode_int(value)
			elif isinstance(value, float):
				value = self.encode_float(value)
			elif isinstance(value, list):
				value = self.encode_array(value, cached_strings)
			elif isinstance(value, list2):
				value = self.encode_object(value, cached_strings)
			elif value == None:
				value = b"\x84"
			else:
				raise TypeError(type(value))
			items.append(key + value)
		return b"\x85" + b"".join(items) + b"\xff"
	def encode_array(self, data, cached_strings):
	# 类型 86
		items = []
		for value in data:
			if isinstance(value, str):
				if "RTID()" == value[:5] + value[-1:]:
					value = self.encode_rtid(value)
				else:
					value = self.encode_cached_string(value, cached_strings)
			elif isinstance(value, bool):
				value = self.encode_bool(value)
			elif isinstance(value, int):
				value = self.encode_int(value)
			elif isinstance(value, float):
				value = self.encode_float(value)
			elif isinstance(value, list):
				value = self.encode_array(value, cached_strings)
			elif isinstance(value, list2):
				value = self.encode_object(value, cached_strings)
			elif value == None:
				value = b"\x84"
			else:
				raise TypeError(type(value))
			items.append(value)
		return b"\x86\xfd" + self.encode_number(len(data)) + b"".join(items) + b"\xfe"
	def encode_cached_string(self, string, cached_strings):
	# 类型 90, 91
		if string in cached_strings:
			return b"\x91" + self.encode_number(cached_strings[string])
		else:
			cached_strings[string] = len(cached_strings)
			encoded_string = string.encode()
			return b"\x90" + self.encode_number(len(encoded_string)) + encoded_string