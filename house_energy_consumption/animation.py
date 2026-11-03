import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import FancyArrowPatch

# Choose version: False = all clients communicate; True = block client 3
block_client3 = False 

client_positions = [(1, 3), (2, 5), (5, 2)]
server_position = (3, 1)

fig, ax = plt.subplots(figsize=(6, 6))
ax.set_xlim(0, 6)
ax.set_ylim(0, 6)
ax.set_aspect('equal')
ax.axis('off')

# Draw clients and server
for i, pos in enumerate(client_positions):
    ax.add_patch(plt.Circle(pos, 0.2, color='blue'))
ax.add_patch(plt.Circle(server_position, 0.3, color='red'))

# Add labels
for idx, pos in enumerate(client_positions, 1):
    ax.text(pos[0], pos[1]+0.3, f'Client {idx}', ha='center', fontsize=12)
ax.text(server_position[0], server_position[1]-0.4, 'Server', ha='center', fontsize=12)

blocked_idx = 2  # Index of client to block (Client 3)

# Draw red X for client 3 if blocked
if block_client3:
    bx, by = client_positions[blocked_idx]
    xsize = 0.2
    ax.plot([bx-xsize, bx+xsize], [by-xsize, by+xsize], color='red', lw=4)
    ax.plot([bx-xsize, bx+xsize], [by+xsize, by-xsize], color='red', lw=4)

# Prepare arrows: one for each client
arrows = []
for idx, pos in enumerate(client_positions):
    if block_client3 and idx == blocked_idx:
        arrows.append(None)
        continue
    arrow = FancyArrowPatch(
        posA=pos, posB=pos,
        arrowstyle='->', mutation_scale=25, color='green', lw=3
    )
    ax.add_patch(arrow)
    arrows.append(arrow)

def interpolate(posA, posB, f):
    return (posA[0] + f*(posB[0]-posA[0]), posA[1] + f*(posB[1]-posA[1]))

def animate(frame):
    n_frames = 40
    phase = (frame % n_frames) / n_frames
    for idx, pos in enumerate(client_positions):
        if block_client3 and idx == blocked_idx:
            continue  # No arrows for blocked client
        if phase < 0.5:
            # Send: arrows grow from client towards server
            f = phase * 2
            start = pos
            end = interpolate(pos, server_position, f)
            arrows[idx].set_positions(start, end)
            arrows[idx].set_color('green')
        else:
            # Response: arrows grow from server towards client
            f = (phase - 0.5) * 2
            start = server_position
            end = interpolate(server_position, pos, f)
            arrows[idx].set_positions(start, end)
            arrows[idx].set_color('orange')
    # Only returning visible arrows for blitting
    return [a for a in arrows if a is not None]

ani = animation.FuncAnimation(fig, animate, frames=80, interval=100, blit=True)
plt.show()