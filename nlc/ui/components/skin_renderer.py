"""
nlc.ui.components.skin_renderer - 3D Minecraft Skin Canvas Renderer
"""

import os
import sys
import math
import logging
from PIL import Image

from nlc.storage.paths import RESAMPLE_NEAREST, AFFINE, FLIP_LEFT_RIGHT

try:
    from skinpy import Skin, BodyPart, Scene # type: ignore
except ImportError:
    Skin = BodyPart = Scene = None

logger = logging.getLogger(__name__)

class SkinRenderer3D:
    @staticmethod
    def render(skin_path, model="classic", height=360):
        try:
            if not os.path.exists(skin_path): return None
            
            src = Image.open(skin_path).convert("RGBA")
            if src.size[0] != 64: 
                temp = Image.new("RGBA", (64, 64))
                temp.paste(src.crop((0,0,64,32)), (0,0))
                temp.paste(src.crop((0,16,16,32)), (16,48)) # Flip leg
                src = temp

            # Try using skinpy (Library: https://github.com/t-mart/skinpy)
            try:
                if 'skinpy' in sys.modules:
                    skin = Skin.from_image(src) # type: ignore

                    # Handle Slim (Alex) Model
                    if model == "slim":
                        # Recreate arms with width=3 (Standard is 4)
                        # Left Arm (Viewer Left / MC Right Arm)
                        # We shift model_origin x from 0 to 1 so it touches torso (at x=4)
                        l_arm = BodyPart.new( # type: ignore
                            id_="left_arm",
                            skin_image_color=skin.image_color,
                            part_shape=(3, 4, 12),
                            part_model_origin=(1, 2, 12),
                            part_image_origin=(40, 16)
                        )
                        # Right Arm (Viewer Right / MC Left Arm)
                        # Stays at x=12 (Torso ends at 12)
                        r_arm = BodyPart.new( # type: ignore
                            id_="right_arm",
                            skin_image_color=skin.image_color,
                            part_shape=(3, 4, 12),
                            part_model_origin=(12, 2, 12),
                            part_image_origin=(32, 48)
                        )
                        
                        # Create new skin with modified arms
                        skin = Skin( # type: ignore
                            image_color=skin.image_color,
                            head=skin.head,
                            torso=skin.torso,
                            left_arm=l_arm,
                            right_arm=r_arm,
                            left_leg=skin.left_leg,
                            right_leg=skin.right_leg
                        )

                    # Use standard isometric perspective with high scaling factor for quality
                    p = Perspective(x="right", y="front", z="up", scaling_factor=10) # type: ignore
                    final = skin.to_isometric_image(p)
                    
                    ratio = final.width / final.height
                    new_h = height
                    new_w = int(new_h * ratio)
                    
                    # Use high quality resampling because we are scaling down/adjusting from high-res (scaling_factor=10)
                    # Try LANCZOS/ANTIALIAS
                    try:
                        rs = Image.Resampling.LANCZOS 
                    except AttributeError:
                        rs = getattr(Image, 'LANCZOS', Image.NEAREST) # type: ignore

                    return final.resize((new_w, new_h), rs)
            except Exception as e:
                print(f"Skinpy render failed: {e}")

            # Base Scale for sharpness
            s = 1 
            # We will process at 1x then resize at end to keep math simple, or use s=4 for quality?
            # Let's use s=2
            s = 2
            src = src.resize((src.width * s, src.height * s), RESAMPLE_NEAREST)
            
            def get_part(x, y, w, h):
                return src.crop((x*s, y*s, (x+w)*s, (y+h)*s))

            # --- Extract Parts ---
            # HEAD
            head_f = get_part(8, 8, 8, 8)
            head_r = get_part(0, 8, 8, 8)
            head_t = get_part(8, 0, 8, 8)
            # Overlay
            head_f.alpha_composite(get_part(40, 8, 8, 8))
            head_r.alpha_composite(get_part(32, 8, 8, 8))
            head_t.alpha_composite(get_part(40, 0, 8, 8))

            # BODY
            body_f = get_part(20, 20, 8, 12)
            body_r = get_part(16, 20, 4, 12)
            body_t = get_part(20, 16, 8, 4)
            # Overlay
            body_f.alpha_composite(get_part(20, 36, 8, 12))
            body_r.alpha_composite(get_part(16, 36, 4, 12))
            body_t.alpha_composite(get_part(20, 32, 8, 4))
            
            # ARMS
            aw = 3 if model=="slim" else 4
            ra_f = get_part(44, 20, aw, 12) # Right Arm Front
            ra_r = get_part(40, 20, 4, 12)  # Right Arm Side (Out)
            ra_t = get_part(44, 16, aw, 4)  # Right Arm Top
            # Overlay
            ra_f.alpha_composite(get_part(44, 36, aw, 12))
            ra_r.alpha_composite(get_part(40, 36, 4, 12))
            ra_t.alpha_composite(get_part(44, 32, aw, 4))

            if src.height == 64*s:
                la_f = get_part(36, 52, aw, 12)
                la_t = get_part(36, 48, aw, 4)
                la_r = get_part(32, 52, 4, 12) # Left Arm In?
                # For Left Arm, the "Side" visible in 3D is usually the outer side.
                # In standard layout:
                # Right Arm: 40,20 (Right/Outer), 44,20 (Front), 48,20 (Inner), 52,20 (Back)
                # Left Arm:  32,52 (Right/Inner), 36,52 (Front), 40,52 (Left/Outer), 44,52 (Back)
                # We want Outer side.
                la_out = get_part(40, 52, 4, 12)
                la_out.alpha_composite(get_part(56, 52, 4, 12))
                
                la_f.alpha_composite(get_part(52, 52, aw, 12))
                la_t.alpha_composite(get_part(52, 48, aw, 4))
            else:
                 # Legacy
                 la_f = ra_f.transpose(FLIP_LEFT_RIGHT)
                 la_t = ra_t.transpose(FLIP_LEFT_RIGHT)
                 la_out = ra_r.transpose(FLIP_LEFT_RIGHT)

            # LEGS
            rl_f = get_part(4, 20, 4, 12)
            rl_r = get_part(0, 20, 4, 12) # Outer Right Leg
            # Overlay
            rl_f.alpha_composite(get_part(4, 36, 4, 12))
            rl_r.alpha_composite(get_part(0, 36, 4, 12))
            
            if src.height == 64*s:
                ll_f = get_part(20, 52, 4, 12)
                # Left Leg: 16,52 (Right/Inner), 20,52 (Front), 24,52 (Left/Outer)
                ll_out = get_part(24, 52, 4, 12)
                # Overlay
                ll_f.alpha_composite(get_part(4, 52, 4, 12)) # Wait, overlay pos defined in skin strict
                # Real overlay for LL: 
                # LL Front: 20,52. Overlay: 4,52 on 64x64? 
                # No, texture mapping says:
                # RL: 0,16->4,20 (Top), 4,20 (Front)
                # LL: 16,48->20,52 (Top), 20,52 (Front)
                # Overlay LL: 0,48? 
                # Let's assume standard layout.
                ll_out.alpha_composite(get_part(8, 52, 4, 12))
            else:
                ll_f = rl_f.transpose(FLIP_LEFT_RIGHT)
                ll_out = rl_r.transpose(FLIP_LEFT_RIGHT)

            # --- ISOMETRIC PROJECTION ---
            def make_iso_block(front, side, top):
                # Standard Isometric blocks
                # Front (Left of spine in 2D): Skew Y = +0.5 x
                # Side (Right of spine in 2D): Skew Y = -0.5 x
                # Actually, in PIL AFFINE, we map Dest -> Src.
                # If we want a line that goes Right & Down (Slope 0.5):
                # y_dest = 0.5 * x_dest.
                # In Source, y_src = y_dest - 0.5 * x_dest.
                # Matrix: (1, 0, 0, -0.5, 1, 0)
                
                w, h = front.size
                d_w, d_h = side.size
                t_w, t_h = top.size
                
                # --- Right Face (Side Texture) ---
                # We see this on the RIGHT of the spine.
                # It should go Down-Right.
                # Shear Matrix: x'=x, y'=y-0.5x. (Standard Iso)
                # PIL Transform: (1, 0, 0, -0.5, 1, 0)
                # Bounding box height increases by 0.5 * width
                
                skew = 0.5
                rH = int(d_h + d_w * skew)
                rW = d_w
                # We need to offset Y so we don't crop negative Y in source?
                # No, x is positive. 0.5 * x is positive. y - pos = smaller y.
                # If y_dest = 0, y_src = 0 - 0 = 0.
                # If y_dest = H, y_src = H.
                # Wait, if x_dest increases, y_src decreases.
                # This means to get y_src=0 at x_dest=W, y_dest must comprise +0.5*W.
                # So the image SLANTS UP (lines go up-right).
                
                # We want lines to go DOWN-RIGHT.
                # So as x increases, y_dest increases.
                # y_dest = y_src + 0.5 x.
                # y_src = y_dest - 0.5 * x.
                # This is correct for Down-Right?
                
                # Let's test. At x=0, y_dest=y_src.
                # At x=W, y_dest = y_src + 0.5W.
                # So the right side is LOWER than the left side. Correct.
                
                side_iso = side.transform((d_w, rH), AFFINE, (1, 0, 0, -skew, 1, 0), RESAMPLE_NEAREST)
                
                # --- Left Face (Front Texture) ---
                # We see this on the LEFT of the spine.
                # It should go Down-Left.
                # If we scan X from Left to Right (0 to W).
                # 0 is the "Left Edge", W is the "Right Edge" (Spine).
                # The Right Edge (Spine) matches the Side.
                # Left Edge is Higher? No, Left Edge is Lower, Right Edge is Lower?
                # In simple Iso Cube V shape:
                # Center Spine is Highest X line? No, Center Vertical is closest to user.
                # Top Center is highest point.
                # Left Face goes Down-Left.
                # Right Face goes Down-Right.
                
                # So for Left Face: As distance from spine (to left) increases, Y increases (goes down).
                # Let's just treat it as a Down-Right skew of a Flipped image?
                # Flip Front -> Down-Right Skew -> Flip Back.
                # If we flip, Left becomes Right. Skew Down-Right (Right side drops).
                # Unflip: Right becomes Left. Left side dropped.
                # Correct.
                
                fH = int(h + w * skew)
                fW = w
                
                # Flip
                front_f = front.transpose(FLIP_LEFT_RIGHT)
                # Skew
                front_s = front_f.transform((fW, fH), AFFINE, (1, 0, 0, -skew, 1, 0), RESAMPLE_NEAREST)
                # Unflip
                front_iso = front_s.transpose(FLIP_LEFT_RIGHT)
                
                # --- Top Face ---
                # Rotate 45 deg, Scale Y 0.5.
                # This makes a diamond.
                # top.rotate expands? YES.
                top_rot = top.rotate(45, expand=True, resample=RESAMPLE_NEAREST)
                # Scale Y
                tH = top_rot.height // 2
                top_iso = top_rot.resize((top_rot.width, tH), RESAMPLE_NEAREST)
                
                # --- Assembly ---
                # Calculate Canvas size
                # Width = Left Width + Right Width
                canvas_w = fW + rW
                # Height = Top Height + Front Height (partially overlapping)
                # Top Diamond Height = tH.
                # Front Vertical Edge = h.
                # Side Vertical Edge = d_h.
                # Total height approx tH/2 + h + tH/2? No.
                
                # Let's find alignment point: "The Center Spine Top".
                # For Top Diamond: Center is (W/2, H/2). Bottom corner is (W/2, H).
                # For Left Face (Front): Top Right corner is (W, 0). (RelativeToImage).
                # But it is skewed.
                # In front_iso (Flipped, Sheared, Flipped):
                # The "Right Edge" (which was Left before flip) is the high edge.
                # Let's trace corners.
                # Front Image (w x h): TL(0,0), TR(w,0), BL(0,h), BR(w,h).
                # Flip: TL->TR.
                # Skew (Down-Right): TR stays (0,0)? No...
                # Skew mapping:
                # (0,0) -> (0,0).
                # (w,0) -> (w, 0.5w). (Dropped).
                # Unflip:
                # The "Left" side of result corresponds to the "Right" side of skewed.
                # Result TL corresponds to Skewed TR ((w, 0.5w)).
                # Result TR corresponds to Skewed TL ((0,0)).
                # So Top-Right corner of front_iso is at (w, 0)? High point.
                # Top-Left corner is at (0, 0.5w)? Low point.
                
                # So Front_Iso: TR is High (y=0 relative to image top?).
                # Ideally, TR should attach to Top Diamond Bottom-Center.
                
                # Side_Iso (Right Face):
                # Skew Down-Right:
                # TL (0,0) -> (0,0). High Point.
                # TR (d_w, 0) -> (d_w, 0.5*d_w). Low Point.
                # So TL is High. attaches to Top Diamond Bottom-Center.
                
                # So Alignment Point is:
                # Top: Bottom Center.
                # Front: Top Right.
                # Side: Top Left.
                
                cx = fW # Spine location in canvas X
                
                # Top Placement
                # Top Center X = cx.
                # Top Width = top_iso.width.
                # We place Top such that its "Bottom" is at the join Y.
                # Top Diamond Bottom is at y = tH.
                # So Top Top-Left is at (cx - top_iso.width//2, join_y - tH).
                
                # Where is Join Y? Let's say Join Y = tH. (So Top starts at 0).
                join_y = tH
                
                # Canvas Height
                # Max drop is from Left Face bottom-left? or Right Face bottom-right?
                # Left Face H = h + 0.5w.
                # Right Face H = d_h + 0.5 d_w.
                # Total H = join_y + max(h, d_h).
                
                canvas_h = join_y + max(h, d_h) + int(max(w, d_w)*0.5) 
                
                can = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
                
                # Paste Top
                can.paste(top_iso, (cx - top_iso.width//2, 0), top_iso)
                offset_top = 0 # Fudges can happen with pixel rounding
                
                # Paste Front (Left of Spine)
                # Position: Right edge at cx. Top edge at join_y.
                # front_iso width is fW.
                can.paste(front_iso, (cx - fW, join_y - offset_top), front_iso)
                
                # Paste Side (Right of Spine)
                # Position: Left edge at cx. Top edge at join_y.
                can.paste(side_iso, (cx, join_y - offset_top), side_iso)
                
                return can

            # --- Compose Character ---
            
            # Make Blocks
            b_head = make_iso_block(head_f, head_r, head_t)
            b_body = make_iso_block(body_f, body_r, body_t)
            # Right Arm (Viewer Left)
            b_ra = make_iso_block(ra_f, ra_r, ra_t)
            # Left Arm (Viewer Right)
            # Use la_out for side (it is the outer side of left arm).
            b_la = make_iso_block(la_f, la_out, la_t)
            # Legs
            b_rl = make_iso_block(rl_f, rl_r, get_part(0,0,4,4)) 
            b_ll = make_iso_block(ll_f, ll_out, get_part(0,0,4,4))
            
            # Canvas
            final_w, final_h = 400 * s // 2, 500 * s // 2
            final = Image.new("RGBA", (final_w, final_h), (0,0,0,0))
            
            # Center of the "Floor"
            mx = final_w // 2
            
            # We align by "Spines".
            # The Spine X of the body is at mx.
            # Head Spine X is mx.
            
            # Y Positioning.
            # Head Top is highest.
            # Let's start Head Top at y=10.
            head_y = 10 * s
            
            # Paste Head
            # b_head spine is at 8*s (Head width).
            # b_head width is 8+8=16 units.
            # We paste so spine is at mx. 
            # Img X for spine is head_f.width.
            # Paste X = mx - head_f.width.
            final.paste(b_head, (mx - head_f.width, head_y), b_head)
            
            # Body
            # Body should be under Head.
            # Neck is where Head Front meets Head Side at the bottom?
            # Head Front Height is 8.
            # But in Iso, height is pure Y? Yes, vertical lines are vertical.
            # So Neck Y = head_y + Top_Diamond_Height + 8*s.
            # Top_Diamond_Height for head (8x8) -> 45deg -> Width approx 11.3 -> Scale Y 0.5 -> Height approx 5.6?
            # Let's count pixels.
            # Top(8,8) -> Rotated Diag is 8*sqrt(2) approx 11.3.
            # Scaled Y 0.5 -> 5.65.
            # So b_head total height = 5.65 + 8 + skew_drop(4).
            # Connection point (Neck) is at "Front Face Top" + 8.
            # In make_iso_block, Front Face Top is at `join_y`.
            # join_y = tH (approx 6s).
            # So Neck Y = head_y + join_y + 8*s.
            
            tH_head = b_head.height - 12*s # approx?
            # Let's use computed join_y from block logic: tH.
            # tH approx 6*s for 8 unit block? 
            # 8*s unit block. 1 unit = s pixels? NO. 
            # get_part multiplies by s.
            # So 8 unit block is 8*s pixels wide.
            # Diag = 1.41 * 8s. Half = 0.7 * 8s = 5.6s.
            # join_y_head approx 6*s.
            
            # Refined Neck Y
            neck_y = head_y + int(5.6 * s) + int(8 * s) # top_h + face_h
            
            # Paste Body
            # Body width (front) is 8*s.
            final.paste(b_body, (mx - body_f.width, neck_y), b_body)
            
            # Legs
            # Leg Y = Neck Y + Body Height (12 units)
            leg_y = neck_y + int(12 * s)
            
            # Right Leg (Viewer Left)
            # Spine is shifted Left by Leg Width (4 units).
            # Because Body Center Spine splits the legs?
            # Standard Skin: RL is 0..4, LL is 4..8.
            # So Body Spine is between legs.
            # RL Spine is at mx - 2*s (Center of RL).
            # Wait, RL is box 4 wide.
            # Its spine (between Front/Side) is at 4 units from its left.
            # We want RL Right Edge to be at mx.
            # So RL Spine is at mx - 2 units? No.
            # RL Front is 0..4 relative to leg.
            # The RL Block has Spine at 4*s (Front Width).
            # We want RL Block Spine to be at mx?
            # If we put RL Spine at mx, then RL Front is left of mx, RL Side is right of mx.
            # But Leg is entirely Left of Center line?
            # Yes, RL is "Right Leg" (Viewer Left).
            # In skin file, RL is x=0..4. Body is x=4..12? No.
            # Body 20..28. RL 4..8.
            # Conceptually, RL is [Center-4, Center].
            # So RL "Right Side" (Inner) is at Center.
            # Our b_rl "Side" is the Outer side (Right of leg).
            # Wait, for RL (Viewer Left), the "Right Side" of the cube is the Outer Side?
            # Yes, standing normally.
            # So RL sits to the Left of MX.
            # Its "Right Edge" (Spine? No)
            # b_rl: [Front][Side]. Spine is between them.
            # Front is Left Face. Side is Right Face.
            # If we place b_rl spine at mx: We see Front (Left of mx) and Side (Right of mx).
            # That would mean RL is centered at mx.
            # But RL should be shifted left.
            # Shift by 2 units (half leg width)? 
            # No, Body is 8 wide. Center is 4.
            # RL is 4 wide. Center is 2.
            # So RL Center is -2 from Body Center.
            # So we shift b_rl by -2 units (-2*s).
            # AND Z-Order?
            # Right Leg is "Viewer Left".
            # Side visible is Outer (Right Side).
            # So we place it such that Spine is at mx - 2*s.
            final.paste(b_rl, (mx - rl_f.width - int(2*s), leg_y), b_rl)
            
            # Left Leg (Viewer Right)
            # Shift Right by 2 units (+2*s).
            # b_ll Spine at mx + 2*s.
            final.paste(b_ll, (mx - ll_f.width + int(2*s), leg_y), b_ll)

            # Arms
            # Arm Y = Neck Y.
            # Right Arm (Viewer Left).
            # Attaches to Body Top-Left-Corner?
            # Body Spine is mx.
            # Body Left Edge is mx - 4*s.
            # RA Right Edge is Body Left Edge?
            # RA width 4 (or 3).
            # RA Spine at mx - 4*s - (Half Arm)?
            # RA Spine is between Front and Side.
            # We want RA "Inner" side to touch Body "Left" Side using blocked space.
            # Ideally: RA Spine is at mx - 6*s. (4 body + 2 arm).
            final.paste(b_ra, (mx - ra_f.width - int(6*s), neck_y), b_ra)
            
            # Left Arm (Viewer Right)
            # Spine at mx + 6*s.
            final.paste(b_la, (mx - la_f.width + int(6*s), neck_y), b_la)

            # --- Finalize ---
            bbox = final.getbbox()
            if bbox:
                final = final.crop(bbox)
                
            ratio = final.width / final.height
            new_h = height
            new_w = int(new_h * ratio)
            return final.resize((new_w, new_h), RESAMPLE_NEAREST)

        except Exception as e:
            print(f"Skin render error: {e}")
            import traceback
            traceback.print_exc()
            return None

# --- Custom Popups ---

