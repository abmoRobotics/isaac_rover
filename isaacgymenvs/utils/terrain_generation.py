from cmath import pi, sqrt
import numpy as np
import math
from isaacgym import gymutil, gymapi
from isaacgym.terrain_utils import *
from scipy.stats import qmc
import random
def cfa(cfa: float, rock_diameter: float):
    # https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/10.1029/96JE03319?download=true
    # https://www.researchgate.net/publication/340235161_Geographic_information_system_based_detection_and_quantification_of_boulders_using_HiRISE_imagery_a_case_study_in_Jezero_Crater
    q = lambda k: 1.79 + (1.52 / k) # Rate at which the total area covered by rocks decreases with increasing diameter q(k)
    Fk = lambda D, k: k * math.exp(-q(k)*D) # The cumulative fractional area covered by rocks larger than D

    return Fk(rock_diameter,cfa)

def add_rocks_terrain(terrain, rock_height = (0.1,0.2)):
    k = 0.15    # total fractional area covered by rocks
    #sample_size = int(0.5 / terrain.horizontal_scale)
    #probs = np.arange(terrain.horizontal_scale, sample_size, terrain.horizontal_scale)
    n_rocks = int(terrain.length * terrain.width * cfa(k,rock_diameter=0.1))
    
    sampler_halton = qmc.Halton(d=2, scramble=False)
    HaltonSample = sampler_halton.random(n=n_rocks)
    HaltonSample[:,0] *= terrain.num_rows
    HaltonSample[:,1] *= terrain.num_cols
    HaltonSample = HaltonSample.astype(int)

    kernel = np.ones((2,2)) * random.uniform(rock_height[0], rock_height[1])

    for p in HaltonSample:
        terrain.height_field_raw[p[1]: p[1]+2, p[0]: p[0]+2] += (kernel*1/terrain.vertical_scale)

    heightfield = np.zeros((terrain.num_rows, terrain.num_cols), dtype=np.float64)




    return terrain

def NormalizeData(data):
    return (data - np.min(data)) / (np.max(data) - np.min(data))

def gaussian_distribution(n_samples: int, sigma=0.3) -> np.ndarray:

    # Discrete sampling of range [-1:1] with n samples
    # With step size 1 / ( (n_samples - 1) / 2 )
    step_size = 2 / (n_samples - 1)
    sampled_values = np.arange(-1, 1+step_size, step_size)

    # Calculate gaussian distribution
    gaussian_distribution = [(1/(sigma*math.sqrt(2*math.pi))) * math.exp(-0.5*(x/sigma)*(x/sigma))   for x in sampled_values]
    
    # Normalize data between 0 and 1
    gaussian_distribution = NormalizeData(gaussian_distribution)

    return gaussian_distribution

def gaussian_kernel(n_samples: int, sigma=0.3) -> np.ndarray:

    # Take the outer product of a gaussian distribution
    gaussian_kernel = np.outer(gaussian_distribution(n_samples,sigma),gaussian_distribution(n_samples,sigma))

    return gaussian_kernel

def gaussian_terrain(terrain):#terrain,gaussian_radius: float,height,n):
    """
    Parameters:
        gaussian_radius (float): Radius of gaussian kernel in meter
        height (float): Maximimum (and minimum) height of terrain
        n (int): Number of kernels per 100m^2
    """
    
    kernel_radius = 15 # radius in meters [m]
    max_height = 5 # Max height in meters [m]

    # Size of kernel size kernel_diameter*kernel_diameter is equal to 2 * kernel_radius [m] / resolution + 1
    kernel_diameter = ((2 * kernel_radius) / terrain.horizontal_scale ) + 1 
    kernel_radius_unitless = ((kernel_diameter - 1) / 2)

    # Get normalized gaussian kernel 
    kernel = gaussian_kernel(kernel_diameter,sigma=0.4)


    n_kernels = int((terrain.length/ (kernel_radius * 2)) * (terrain.width/ (kernel_radius * 2)))

    # Generate random placement of kernels
    sampler_halton = qmc.Halton(d=2, scramble=False)
    HaltonSample = sampler_halton.random(n=n_kernels)
    HaltonSample[:,0] *= terrain.num_rows
    HaltonSample[:,1] *= terrain.num_cols
    HaltonSample = HaltonSample.astype(int)
    gaussian_heightfield = np.zeros((terrain.num_rows, terrain.num_cols), dtype=np.int16)
    
   # HaltonSample = [[90,90]]
    for i in range(len(HaltonSample)):
        from_x = int( max(0, HaltonSample[i,0]-kernel_radius_unitless) )
        to_x = int( min(terrain.num_rows, HaltonSample[i,0]+kernel_radius_unitless) )
        from_y = int( max(0, HaltonSample[i,1]-kernel_radius_unitless) )
        to_y = int( min(terrain.num_cols, HaltonSample[i,1]+kernel_radius_unitless) )

        from_x_kernel = int( abs(min(0, HaltonSample[i,0]-kernel_radius_unitless)) )
        to_x_kernel = int(  abs(min(kernel_diameter-1,terrain.num_rows-(HaltonSample[i,0]-kernel_radius_unitless))) )
        from_y_kernel = int( abs(min(0, HaltonSample[i,1]-kernel_radius_unitless)) )
        to_y_kernel = int(  abs(min(kernel_diameter-1,terrain.num_cols-(HaltonSample[i,1]-kernel_radius_unitless))) )

        # Fixed height
        #terrain.height_field_raw[from_y: to_y, from_x: to_x] += (kernel[from_y_kernel:to_y_kernel,from_x_kernel:to_x_kernel] * max_height* 1/terrain.vertical_scale )

        # Random height
        terrain.height_field_raw[from_y: to_y, from_x: to_x] += (kernel[from_y_kernel:to_y_kernel,from_x_kernel:to_x_kernel] * random.uniform(-max_height,max_height)* 1/terrain.vertical_scale )
       # print(HaltonSample[i])

    return terrain

def convert_heightfield_to_trimesh1(height_field_raw, horizontal_scale, vertical_scale, slope_threshold=None):
    """
    Convert a heightfield array to a triangle mesh represented by vertices and triangles.
    Optionally, corrects vertical surfaces above the provide slope threshold:

        If (y2-y1)/(x2-x1) > slope_threshold -> Move A to A' (set x1 = x2). Do this for all directions.
                   B(x2,y2)
                  /|
                 / |
                /  |
        (x1,y1)A---A'(x2',y1)

    Parameters:
        height_field_raw (np.array): input heightfield
        horizontal_scale (float): horizontal scale of the heightfield [meters]
        vertical_scale (float): vertical scale of the heightfield [meters]
        slope_threshold (float): the slope threshold above which surfaces are made vertical. If None no correction is applied (default: None)
    Returns:
        vertices (np.array(float)): array of shape (num_vertices, 3). Each row represents the location of each vertex [meters]
        triangles (np.array(int)): array of shape (num_triangles, 3). Each row represents the indices of the 3 vertices connected by this triangle.
    """
    hf = height_field_raw
    num_rows = hf.shape[0]
    num_cols = hf.shape[1]
    y = np.linspace(0, (num_cols-1)*horizontal_scale, num_cols)
    x = np.linspace(0, (num_rows-1)*horizontal_scale, num_rows)
    yy, xx = np.meshgrid(y, x)
    if slope_threshold is not None:

        slope_threshold *= horizontal_scale / vertical_scale
        move_x = np.zeros((num_rows, num_cols))
        move_y = np.zeros((num_rows, num_cols))
        move_corners = np.zeros((num_rows, num_cols))
        move_x[:num_rows-1, :] += (hf[1:num_rows, :] - hf[:num_rows-1, :] > slope_threshold)
        move_x[1:num_rows, :] -= (hf[:num_rows-1, :] - hf[1:num_rows, :] > slope_threshold)
        move_y[:, :num_cols-1] += (hf[:, 1:num_cols] - hf[:, :num_cols-1] > slope_threshold)
        move_y[:, 1:num_cols] -= (hf[:, :num_cols-1] - hf[:, 1:num_cols] > slope_threshold)
        move_corners[:num_rows-1, :num_cols-1] += (hf[1:num_rows, 1:num_cols] - hf[:num_rows-1, :num_cols-1] > slope_threshold)
        move_corners[1:num_rows, 1:num_cols] -= (hf[:num_rows-1, :num_cols-1] - hf[1:num_rows, 1:num_cols] > slope_threshold)
        xx += (move_x + move_corners*(move_x == 0)) * horizontal_scale
        yy += (move_y + move_corners*(move_y == 0)) * horizontal_scale

    # create triangle mesh vertices and triangles from the heightfield grid
    vertices = np.zeros((num_rows*num_cols, 3), dtype=np.float32)
    vertices[:, 0] = xx.flatten()
    vertices[:, 1] = yy.flatten()
    vertices[:, 2] = hf.flatten() * vertical_scale
    triangles = -np.ones((2*(num_rows-1)*(num_cols-1), 3), dtype=np.uint32)
    for i in range(num_rows - 1):
        ind0 = np.arange(0, num_cols-1) + i*num_cols
        ind1 = ind0 + 1
        ind2 = ind0 + num_cols
        ind3 = ind2 + 1
        start = 2*i*(num_cols-1)
        stop = start + 2*(num_cols-1)
        triangles[start:stop:2, 0] = ind0
        triangles[start:stop:2, 1] = ind3
        triangles[start:stop:2, 2] = ind1
        triangles[start+1:stop:2, 0] = ind0
        triangles[start+1:stop:2, 1] = ind2
        triangles[start+1:stop:2, 2] = ind3

    return vertices, triangles


class SubTerrain1:
    def __init__(self, terrain_name="terrain", width=256, length=256, vertical_scale=1.0, horizontal_scale=1.0):
        self.terrain_name = terrain_name
        self.vertical_scale = vertical_scale
        self.horizontal_scale = horizontal_scale
        self.width = width
        self.length = length
        self.num_rows = int(self.width/self.horizontal_scale)
        self.num_cols = int(self.length/horizontal_scale)
        self.height_field_raw = np.zeros((self.num_rows, self.num_cols), dtype=np.float64)


def VisualTest():

    # initialize gym
    gym = gymapi.acquire_gym()

    # parse arguments
    args = gymutil.parse_arguments()

    # configure sim
    sim_params = gymapi.SimParams()
    sim_params.up_axis = gymapi.UpAxis.UP_AXIS_Z
    sim_params.gravity = gymapi.Vec3(0.0, 0.0, -9.81)

    if args.physics_engine == gymapi.SIM_FLEX:
        print("WARNING: Terrain creation is not supported for Flex! Switching to PhysX")
        args.physics_engine = gymapi.SIM_PHYSX
    sim_params.substeps = 2
    sim_params.physx.solver_type = 1
    sim_params.physx.num_position_iterations = 4
    sim_params.physx.num_velocity_iterations = 0
    sim_params.physx.num_threads = args.num_threads
    sim_params.physx.use_gpu = args.use_gpu

    sim = gym.create_sim(args.compute_device_id, args.graphics_device_id, args.physics_engine, sim_params)
    if sim is None:
        print("*** Failed to create sim")
        quit()

    ### CUSTOM


    # create all available terrain types
    terrain_width = 40 # terrain width [m]
    terrain_length = 40 # terrain length [m]
    horizontal_scale = 0.1 # resolution per meter 
    vertical_scale = 0.005 # vertical resolution [m]
    heightfield = np.zeros((int(terrain_width/horizontal_scale), int(terrain_length/horizontal_scale)), dtype=np.int16)
  
    def new_sub_terrain(): return SubTerrain1(width=terrain_width,length=terrain_length,horizontal_scale=horizontal_scale,vertical_scale=vertical_scale)
    #terrain = gaussian_terrain(new_sub_terrain())
    #heightfield[0:int(terrain_width/horizontal_scale),:]= gaussian_terrain(new_sub_terrain()).height_field_raw
    heightfield[0:int(terrain_width/horizontal_scale),:]= add_rocks_terrain(terrain=new_sub_terrain()).height_field_raw
    vertices, triangles = convert_heightfield_to_trimesh1(heightfield, horizontal_scale=horizontal_scale, vertical_scale=vertical_scale, slope_threshold=0.15)
   # print(vertices[:])
    #print(vertices.pop(1).shape)

    # a = np.array([[0.1, 0.1 , 1.0]],dtype=np.float32)
    # b = np.array([[0.11, 0.1 , 1.0]],dtype=np.float32)
    # c = np.array([[0.11, 0.11 , 1.0]],dtype=np.float32)
    # d = np.array([[160000, 160001 , 160002]],dtype=np.uint32)
    # vertices = np.append(vertices, a, axis=0)
    # vertices = np.append(vertices, b, axis=0)
    # vertices = np.append(vertices, c, axis=0)

    # triangles = np.append(triangles, d, axis=0)

     ### CUSTOM

    tm_params = gymapi.TriangleMeshParams()
    tm_params.nb_vertices = vertices.shape[0]
    tm_params.nb_triangles = triangles.shape[0]
    tm_params.transform.p.x = -1.
    tm_params.transform.p.y = -1.
    gym.add_triangle_mesh(sim, vertices.flatten(), triangles.flatten(), tm_params)
    # create viewer
    viewer = gym.create_viewer(sim, gymapi.CameraProperties())
    if viewer is None:
        print("*** Failed to create viewer")
        quit()

    cam_pos = gymapi.Vec3(-5, -5, 15)
    cam_target = gymapi.Vec3(0, 0, 10)
    gym.viewer_camera_look_at(viewer, None, cam_pos, cam_target)

    # subscribe to spacebar event for reset
    gym.subscribe_viewer_keyboard_event(viewer, gymapi.KEY_R, "reset")

    while not gym.query_viewer_has_closed(viewer):

        # Get input actions from the viewer and handle them appropriately
        for evt in gym.query_viewer_action_events(viewer):
            if evt.action == "reset" and evt.value > 0:
                gym.set_sim_rigid_body_states(sim, initial_state, gymapi.STATE_ALL)

        # step the physics
        gym.simulate(sim)
        gym.fetch_results(sim, True)

        # update the viewer
        gym.step_graphics(sim)
        gym.draw_viewer(viewer, sim, True)

        # Wait for dt to elapse in real time.
        # This synchronizes the physics simulation with the rendering rate.
        gym.sync_frame_time(sim)

    gym.destroy_viewer(viewer)
    gym.destroy_sim(sim)

if __name__=="__main__":
    terrain_width = 100 # terrain width [m]
    terrain_length = 100 # terrain length [m]
    horizontal_scale = 0.1 # resolution per meter 
    vertical_scale = 0.005 # vertical resolution [m]
    #heightfield = np.zeros((int(terrain_width/horizontal_scale), int(terrain_length/horizontal_scale)), dtype=np.int16)
    VisualTest()
    #def new_sub_terrain(): return SubTerrain1(width=terrain_width,length=terrain_length,horizontal_scale=horizontal_scale,vertical_scale=vertical_scale)
    #add_rocks_terrain(terrain=new_sub_terrain())
else:
    pass