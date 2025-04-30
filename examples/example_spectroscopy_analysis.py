#!/usr/bin/env python3
"""
Gaseous Particle Array Simulation

This script simulates particles in a 2D box with elastic collisions
between particles and walls.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import matplotlib.patches as patches

# Simulation parameters
num_particles = 50  # Number of particles
box_size = 10.0     # Box dimensions (square)
particle_radius = 0.2
max_speed = 0.1     # Maximum initial speed

# Particle properties: position, velocity, mass
positions = np.random.uniform(particle_radius, box_size - particle_radius, size=(num_particles, 2))
velocities = np.random.uniform(-max_speed, max_speed, size=(num_particles, 2))
masses = np.ones(num_particles)  # All particles have the same mass

# Setup the plot
fig, ax = plt.subplots(figsize=(8, 8))
ax.set_xlim(0, box_size)
ax.set_ylim(0, box_size)
ax.set_aspect('equal')
ax.set_title('Gas Particle Simulation')

# Create box borders
box = patches.Rectangle((0, 0), box_size, box_size, linewidth=2, 
                      edgecolor='black', facecolor='none')
ax.add_patch(box)

# Create particles (circles)
circles = [plt.Circle((positions[i, 0], positions[i, 1]), 
                     particle_radius, color='blue', alpha=0.7) 
          for i in range(num_particles)]

for circle in circles:
    ax.add_patch(circle)

# Text for displaying kinetic energy
energy_text = ax.text(0.02, 0.95, '', transform=ax.transAxes)

def update(frame):
    global positions, velocities
    
    # Update positions
    positions += velocities
    
    # Check for collisions with walls
    # Left and right walls
    wall_collision_x = (positions[:, 0] <= particle_radius) | (positions[:, 0] >= box_size - particle_radius)
    velocities[wall_collision_x, 0] *= -1  # Reverse x velocity
    
    # Top and bottom walls
    wall_collision_y = (positions[:, 1] <= particle_radius) | (positions[:, 1] >= box_size - particle_radius)
    velocities[wall_collision_y, 1] *= -1  # Reverse y velocity
    
    # Keep particles inside the box
    positions[:, 0] = np.clip(positions[:, 0], particle_radius, box_size - particle_radius)
    positions[:, 1] = np.clip(positions[:, 1], particle_radius, box_size - particle_radius)
    
    # Check for collisions between particles
    for i in range(num_particles):
        for j in range(i+1, num_particles):
            # Calculate distance between particles
            dx = positions[j, 0] - positions[i, 0]
            dy = positions[j, 1] - positions[i, 1]
            distance = np.sqrt(dx**2 + dy**2)
            
            # Check if particles overlap (collision)
            if distance <= 2 * particle_radius:
                # Collision handling with elastic collision physics
                # Normal direction
                nx = dx / distance
                ny = dy / distance
                
                # Relative velocity
                dvx = velocities[j, 0] - velocities[i, 0]
                dvy = velocities[j, 1] - velocities[i, 1]
                
                # Project velocity onto normal direction
                vn = dvx * nx + dvy * ny
                
                # Ignore if particles are moving away from each other
                if vn < 0:
                    # Impulse formula for elastic collision
                    impulse = 2 * vn / (1/masses[i] + 1/masses[j])
                    
                    # Apply impulse
                    velocities[i, 0] += impulse * nx / masses[i]
                    velocities[i, 1] += impulse * ny / masses[i]
                    velocities[j, 0] -= impulse * nx / masses[j]
                    velocities[j, 1] -= impulse * ny / masses[j]
                    
                    # Move particles slightly to avoid overlap
                    overlap = 2 * particle_radius - distance
                    positions[i, 0] -= overlap * nx / 2
                    positions[i, 1] -= overlap * ny / 2
                    positions[j, 0] += overlap * nx / 2
                    positions[j, 1] += overlap * ny / 2
    
    # Update circle positions
    for i, circle in enumerate(circles):
        circle.center = positions[i, 0], positions[i, 1]
    
    # Calculate and display kinetic energy
    kinetic_energy = 0.5 * np.sum(masses[:, np.newaxis] * velocities**2)
    energy_text.set_text(f'Kinetic Energy: {kinetic_energy:.2f}')
    
    return circles + [energy_text]

# Create animation
animation = FuncAnimation(fig, update, frames=500, interval=20, blit=True)

plt.tight_layout()
plt.show()