import minecraft_launcher_lib
import inspect

print("Fabric module attributes:")
try:
    print(dir(minecraft_launcher_lib.fabric))
except:
    print("No fabric module directly")

print("\nForge module attributes:")
try:
    print(dir(minecraft_launcher_lib.forge))
except:
    print("No forge module directly")
