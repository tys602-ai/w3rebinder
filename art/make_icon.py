"""Draw the W3 KeyBinder icon: a dark keyboard keycap with a gold W3 legend."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

S = 1024
OUT = "/home/user/w3keybinder/w3keybinder/assets"
FONT = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"


def vgrad(w, h, top, bottom):
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4))
        for x in range(w):
            px[x, y] = c
    return g


def rmask(box, r):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    return m


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# soft shadow under the key
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle((110, 170, 914, 990), 170, fill=(0, 0, 0, 170))
img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(28)))

# key base ("skirt"): darker, gives the 3D keycap look
base_box = (84, 96, 940, 950)
base = vgrad(S, S, (58, 58, 62, 255), (14, 14, 16, 255))
img.paste(base, (0, 0), rmask(base_box, 170))
ImageDraw.Draw(img).rounded_rectangle(base_box, 170, outline=(92, 92, 98, 255), width=10)

# top face: slightly inset and raised
top_box = (164, 140, 860, 800)
top = vgrad(S, S, (70, 70, 76, 255), (34, 34, 38, 255))
img.paste(top, (0, 0), rmask(top_box, 120))
d = ImageDraw.Draw(img)
d.rounded_rectangle(top_box, 120, outline=(110, 110, 118, 255), width=6)
# highlight along the top edge of the face
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(hl).rounded_rectangle((180, 152, 844, 300), 100, fill=(255, 255, 255, 26))
img = Image.alpha_composite(img, hl)

# thin gold inset line on the face
gold_line = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(gold_line).rounded_rectangle((204, 180, 820, 760), 92, outline=(216, 178, 90, 120), width=6)
img = Image.alpha_composite(img, gold_line)

# gold "W3" legend with a dark edge
font = ImageFont.truetype(FONT, 400)
text = "W3"
bbox = font.getbbox(text)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
cx, cy = (top_box[0] + top_box[2]) // 2, (top_box[1] + top_box[3]) // 2
tx, ty = cx - tw // 2 - bbox[0], cy - th // 2 - bbox[1] + 6
tmask = Image.new("L", (S, S), 0)
ImageDraw.Draw(tmask).text((tx, ty), text, font=font, fill=255)
edge = tmask.filter(ImageFilter.MaxFilter(15))
dark = Image.new("RGBA", (S, S), (20, 14, 4, 255))
img.paste(dark, (0, 0), edge)
gold = vgrad(S, S, (250, 226, 150, 255), (176, 128, 40, 255))
img.paste(gold, (0, 0), tmask)
# small shine on the letters
shine = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shine).rectangle((0, 0, S, cy - 40), fill=(255, 255, 255, 45))
shine.putalpha(ImageChops.multiply(shine.getchannel("A"), tmask))
img = Image.alpha_composite(img, shine)

img.save("art/icon_1024.png")
img.resize((256, 256), Image.LANCZOS).save(f"{OUT}/icon.png")
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(f"{OUT}/icon.ico", sizes=sizes)
# preview sheet: big + the small sizes on light and dark backgrounds
sheet = Image.new("RGBA", (900, 420), (240, 240, 240, 255))
dk = Image.new("RGBA", (450, 420), (32, 32, 32, 255))
sheet.paste(dk, (450, 0))
x = 20
big = img.resize((256, 256), Image.LANCZOS)
sheet.alpha_composite(big, (20, 20)); sheet.alpha_composite(big, (470, 20))
for n in (64, 48, 32, 24, 16):
    sm = img.resize((n, n), Image.LANCZOS)
    sheet.alpha_composite(sm, (x, 320)); sheet.alpha_composite(sm, (450 + x, 320))
    x += n + 24
sheet.save("/tmp/claude-0/-home-user/e5f2ae4a-e2f5-51f3-b36f-1abc2dae051c/scratchpad/icon_preview.png")
print("done")


# ---- simplified version for 16-32 px: fuller key, bigger letters, no inner line ----
small = Image.new("RGBA", (S, S), (0, 0, 0, 0))
sb = (24, 40, 1000, 1000)
small.paste(vgrad(S, S, (64, 64, 70, 255), (14, 14, 16, 255)), (0, 0), rmask(sb, 190))
ImageDraw.Draw(small).rounded_rectangle(sb, 190, outline=(120, 120, 128, 255), width=26)
tb = (90, 70, 934, 860)
small.paste(vgrad(S, S, (78, 78, 84, 255), (36, 36, 40, 255)), (0, 0), rmask(tb, 150))
f2 = ImageFont.truetype(FONT, 560)
bb = f2.getbbox("W3")
w2, h2 = bb[2] - bb[0], bb[3] - bb[1]
cx2, cy2 = (tb[0] + tb[2]) // 2, (tb[1] + tb[3]) // 2
m2 = Image.new("L", (S, S), 0)
ImageDraw.Draw(m2).text((cx2 - w2 // 2 - bb[0], cy2 - h2 // 2 - bb[1]), "W3", font=f2, fill=255)
small.paste(Image.new("RGBA", (S, S), (20, 14, 4, 255)), (0, 0), m2.filter(ImageFilter.MaxFilter(21)))
small.paste(vgrad(S, S, (255, 232, 160, 255), (196, 146, 52, 255)), (0, 0), m2)

frames = {n: (small if n <= 32 else img).resize((n, n), Image.LANCZOS) for n in (16, 24, 32, 48, 64, 128, 256)}
frames[256].save(f"{OUT}/icon.ico", sizes=[(n, n) for n in frames],
                 append_images=[frames[n] for n in (16, 24, 32, 48, 64, 128)])
check = Image.open(f"{OUT}/icon.ico")
print("ico sizes:", sorted(check.info.get("sizes", [])))
sheet = Image.new("RGBA", (520, 120), (240, 240, 240, 255))
sheet.paste(Image.new("RGBA", (260, 120), (32, 32, 32, 255)), (260, 0))
x = 16
for n in (48, 32, 24, 16):
    for off in (0, 260):
        sheet.alpha_composite(frames[n], (off + x, 40))
    x += n + 18
sheet = sheet.resize((1040, 240), Image.NEAREST)
sheet.save("/tmp/claude-0/-home-user/e5f2ae4a-e2f5-51f3-b36f-1abc2dae051c/scratchpad/icon_small_preview.png")
