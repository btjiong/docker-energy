import os, sys, getopt, subprocess, random, re, time, math, yaml, psutil
from datetime import datetime


class Workload:
    def __init__(
        self,
        exp_id: str,
        name: str,
        images: set,
        queue: list,
        isolate_cpus: str,
        background_cpus: str,
        threads: int,
        warmup: int,
        pause: int,
        interval: int,
        clients: int,
        monitor: str,
        docker: bool,
        command: str,
    ):
        self.exp_id = exp_id
        self.name = name
        self.images = images
        self.queue = queue
        self.isolate_cpus = isolate_cpus
        self.background_cpus = background_cpus
        self.threads = threads
        self.warmup = warmup
        self.pause = pause
        self.interval = interval
        self.clients = clients
        self.monitor = monitor
        self.docker = docker
        self.command = command

    def prepare(self):
        # Execute the given command
        command = [
            "bash",
            "scripts/prepare",
            "-x",
            self.exp_id,
            "-l",
            self.name,
            "-i",
            self.isolate_cpus,
            "-j",
            self.background_cpus,
            "-t",
            str(self.threads),
            "-w",
            str(self.warmup),
            "-d",
            str(self.docker),
            "-c",
            self.command,
        ]
        for image in self.images:
            command += ["-b", image]
        subprocess.call(command)

    def run(self):
        # Current execution number in total
        total = 1

        command = [
            "bash",
            "scripts/monitor",
            "-x",
            self.exp_id,
            "-l",
            self.name,
            "-i",
            self.isolate_cpus,
            "-j",
            self.background_cpus,
            "-t",
            str(self.threads),
            "-p",
            str(self.pause),
            "-v",
            str(self.interval),
            "-m",
            self.monitor,
            "-d",
            str(self.docker),
            "-c",
            self.command,
        ]

        if self.clients > 0:
            command += ["-s", str(self.clients)]

        # Monitor the selected images for the selected number of times in regular order
        for image in self.queue:
            # Execute the monitoring script;
            # -r is the current run for the image;
            # -t is the current run in total
            run_command = command + ["-b", image, "-r", str(total)]
            subprocess.call(run_command)
            total += 1

    def remove(self):
        command = ["bash", "scripts/remove", "-x", self.exp_id, "-l", self.name]
        for image in self.images:
            command += ["-b", image]
        subprocess.call(command)


def init_queue(images, runs, shuffle_mode):
    """Initializes the queue based on the images, the number of runs, and order.

    Args:
        images: The images to monitor for this workload.
        runs: The number of runs per image.
        shuffle_mode: Whether to shuffle the order of the images.

    Returns:
        The queue of images to monitor.
    """
    queue = list()
    for image in images:
        queue += [image] * int(runs)
    if shuffle_mode:
        random.shuffle(queue)
    return queue


def set_cpus(cpus):
    """Sets the cpuset for the workload if no cpuset is provided, but the number of threads is.

    Args:
        cpus: The number of threads to isolate for the workload

    Returns:
        The cpuset and the reserved threads (i.e. threads that are not used at all).
    """
    # Get the number of physical and logical CPUs
    physical_cpus = psutil.cpu_count(logical=False)
    logical_cpus = psutil.cpu_count()

    # Allocate the logical CPUs to the physical CPUs
    dict_cpus = {x: [] for x in range(physical_cpus)}
    core = 0
    for x in range(logical_cpus):
        dict_cpus[core].append(x)
        core += 1
        if core >= physical_cpus:
            core = 0

    # Isolate the amount of threads on the same physical CPU
    cpuset = list()
    reserve = list()
    threads = logical_cpus / physical_cpus
    for x in range(math.ceil(cpus / threads)):
        cpuset.extend(dict_cpus[x])

    # Reserve the remaining threads on a physical CPU
    for x in range(len(cpuset) - cpus):
        reserve.append(cpuset.pop())

    # Convert the list to a string
    cpuset = ",".join([str(x) for x in cpuset])
    return cpuset, reserve


def set_cpuset(cpuset, reserve=[]):
    """Defines the set of threads for the workload and the background processes.

    Args:
        cpuset: The cpuset to use for the workload.
        reserve: The threads on the isolated cores that are not used.

    Returns:
        The cpuset for the workload, the cpuset for the background processes, and the number of threads for the workload.
    """
    isolate_cpus = set()
    background_cpus = set(range(psutil.cpu_count()))

    # Remove the reserved CPUs from the available CPUs
    for x in reserve:
        background_cpus.remove(x)

    # If no cpuset is specified, use all available CPUs
    if cpuset == "":
        isolate_cpus = ",".join(str(i) for i in list(background_cpus))
        background_cpus = ",".join(str(i) for i in list(background_cpus))
        threads = len(isolate_cpus)
        return isolate_cpus, background_cpus, threads

    # If a cpuset is specified, isolate the specified CPUs
    total_cpus = set(range(psutil.cpu_count()))
    cpuset = cpuset.replace(" ", "").split(",")
    for cpu in cpuset:
        # If a range is specified, isolate the range
        if "-" in cpu:
            cpu_range = re.split("-", cpu)
            try:
                # If the range is valid, isolate the range
                if int(cpu_range[0]) in total_cpus and int(cpu_range[-1]) in total_cpus:
                    isolate_cpus |= set(
                        range(int(cpu_range[0]), int(cpu_range[-1]) + 1)
                    )
                    background_cpus -= set(
                        range(int(cpu_range[0]), int(cpu_range[-1]) + 1)
                    )
            except ValueError:
                print("Invalid CPU range")
        else:
            try:
                # If the CPU is valid, isolate the CPU
                if int(cpu) in total_cpus:
                    isolate_cpus.add(int(cpu))
                    background_cpus.remove(int(cpu))
            except:
                print("Invalid CPU")

    # If no CPUs are isolated or all CPUs are isolated, use all available CPUs
    if len(background_cpus) == 0 or len(isolate_cpus) == 0:
        isolate_cpus = set(range(psutil.cpu_count()))
        background_cpus = set(range(psutil.cpu_count()))

    # Convert the sets to strings
    threads = len(isolate_cpus)
    isolate_cpus = ",".join(str(i) for i in list(isolate_cpus))
    background_cpus = ",".join(str(i) for i in list(background_cpus))

    return isolate_cpus, background_cpus, threads


def get_workloads(directory: str):
    """Returns the workloads in the given directory.

    Args:
        directory: The directory to search for workloads.

    Returns:
        The workloads in the given directory.
    """    
    try:
        return [
            workload
            for workload in os.listdir(directory)
            if os.path.isdir(f"{directory}/{workload}")
        ]
    except FileNotFoundError:
        print(f"Directory {directory} not found")
        return []


def get_workload_config(workload: str):
    """Returns the configuration of the given workload.

    Args:
        workload: The workload to get the configuration for.

    Returns:
        The configuration of the given workload.
    """    
    with open(f"workloads/{workload}/config.yml", "r") as file:
        config = yaml.safe_load(file)
    return config


def help():
    print(
        "A tool for measuring energy consumption for specific workloads using different base images.\n",
        "Options:",
        "   -l --workload       Workload to monitor; can be used to for multiple workloads (e.g. -l llama.cpp -l mattermost)",
        '   -b --base           Base image to monitor; can be used for multiple base images (e.g. -b ubuntu -b alpine)',
        "   -n --runs           Number of monitoring runs per base image (e.g. -n 30) (default 30)",
        "   -w --warmup         Warm up time (multiplied by the number of cores in seconds) (e.g. -w 30) (default 10)",
        "   -p --pause          Pause time (s) (e.g. -p 60) (default 20)",
        "   -i --interval       Interval of monitoring (ms) (e.g. -i 100) (default 100)",
        '   -m --monitor        Monitoring tool (e.g. -m "perf") (default "greenserver")',
        "   --no-shuffle        Disables shuffle mode; regular order of monitoring base images",
        "   --cpus              Number of CPUs to isolate; will use threads on the same physical core (e.g. --cpus 2)",
        "   --cpuset            CPUs to isolate (e.g. --cpuset 0-1)",
        "   --all-images        Monitor all compatible base images (defined in the corresponding config file)",
        "   --all-workloads     Monitor all compatible workloads (defined in the workloads directory)",
        "   --full              Monitor all compatible workloads using all compatible base images",
        sep=os.linesep,
    )


def parse_args(argv):
    # Default values
    workloads = set()
    images = set()
    runs = 30 # number of runs per image
    warmup = 15 # (warmup * cores) seconds of warm up time
    pause = 20 # seconds of pause between runs
    interval = 100 # ms of interval between measurements
    monitor = "" # monitoring tool (default: greenserver)
    shuffle_mode = True # shuffle the order of the images
    help_mode = False # show the help menu
    cpus = 0 # number of cpus to dedicate only to the workload
    cpuset = "" # cpus to dedicate only to the workload
    all_images = False # monitor all compatible images
    all_workloads = False # monitor all compatible workloads

    # Get the arguments provided by the user
    opts, args = getopt.getopt(
        argv,
        "l:"  # workload
        "b:"  # base image
        "n:"  # number of runs
        "w:"  # warm up time
        "p:"  # pause time
        "i:"  # interval of monitoring
        "m:"  # monitoring tool
        "s"  # shuffle mode
        "h",  # help
        [
            "workload=",
            "base=",
            "runs=",
            "warmup=",
            "pause=",
            "interval=",
            "monitor=",
            "no-shuffle",
            "cpus=",
            "cpuset=",
            "all-images",
            "all-workloads",
            "full",
            "help",
        ],
    )
    for opt, arg in opts:
        if opt in ["-l", "--workload"]:
            workloads.add(arg)
        # Add the images to the list and the preparation command
        elif opt in ["-b", "--base"]:
            if ":" not in arg:  # If no version is specified, use the latest
                arg += ":latest"
            elif (
                arg[-1] == ":"
            ):  # If the version is specified but empty, use the latest
                arg += "latest"
            if arg not in images:
                images.add(arg)
        # Set the number of runs
        elif opt in ["-n", "--runs"]:
            try:
                runs = int(arg)
            except ValueError:
                print(f"Number of runs must be an integer; using default value ({runs}))")
        # Set up the warm up time (s)
        elif opt in ["-w", "--warmup"]:
            try:
                warmup = int(arg)
            except ValueError:
                print(f"Warm up time must be an integer; using default value ({warmup})")
        # Set up the pause time (s)
        elif opt in ["-p", "--pause"]:
            try:
                pause = int(arg)
            except ValueError:
                print(f"Pause time must be an integer; using default value ({pause})")
        elif opt in ["-i", "--interval"]:
            try:
                interval = int(arg)
            except ValueError:
                print(f"Interval time must be an integer; using default value ({interval})")
        # Set the monitoring tool
        elif opt in ["-m", "--monitor"]:
            monitor = arg
        # Set shuffle mode to false
        elif opt in ["-s", "--no-shuffle"]:
            shuffle_mode = False
        # Add the images to the list and the preparation command
        elif opt == "--cpus":
            try:
                cpus = int(arg)
            except ValueError:
                print("Number of CPUs must be an integer")
        elif opt == "--cpuset":
            cpuset = arg
        # Add all (pre-selected) images to the image set
        elif opt == "--all-images":
            all_images = True
        elif opt == "--all-workloads":
            # workloads |= set(get_workloads("workloads"))
            all_workloads = True
        elif opt == "--full":
            all_images = True
            all_workloads = True
        # Set help mode to true
        elif opt in ["-h", "--help"]:
            help_mode = True

    # Put the arguments in a dictionary
    arguments = {
        "workloads": workloads,
        "images": images,
        "runs": runs,
        "warmup": warmup,
        "pause": pause,
        "interval": interval,
        "monitor": monitor,
        "shuffle_mode": shuffle_mode,
        "cpus": cpus,
        "cpuset": cpuset,
        "all_images": all_images,
        "all_workloads": all_workloads,
        "help_mode": help_mode,
    }
    return arguments


def main(argv):
    # Get the arguments from the command
    arguments = parse_args(argv)

    # If help mode is enabled, do not monitor and open the help menu
    if arguments["help_mode"]:
        help()
        return

    # If no specific workload is selected, monitor all available workloads
    if len(arguments["workloads"]) == 0 and not arguments["all_workloads"]:
        print("No workload provided, all workloads will be used")
        arguments["all_workloads"] = True

    # If no specific image is selected, monitor all available images for the selected workloads
    if len(arguments["images"]) == 0 and not arguments["all_images"]:
        print("No base images provided, all images will be used")
        arguments["all_images"] = True

    workloads = get_workloads("workloads")

    # If specific workloads are selected, monitor only those workloads if they are available
    if not arguments["all_workloads"]:
        workloads = set(workloads).intersection(arguments["workloads"])
    
    date = datetime.now().strftime("%Y%m%dT%H%M%S")

    for workload in workloads:
        config = get_workload_config(workload)

        # Skip development workloads
        if "development" in config.keys() and config["development"]:
            continue

        # First set the cpuset
        if arguments["cpuset"] != "":
            cpuset = arguments["cpuset"]
            reserve = []
        # If no cpuset is provided, use the number of cpus
        elif arguments["cpus"] != 0:
            cpuset, reserve = set_cpus(arguments["cpus"])
        # If no cpus are provided, use the cpus from the config
        elif "cpus" in config.keys() and type(config["cpus"]) is int:
            cpuset, reserve = set_cpus(config["cpus"])
        # If no cpus are provided in the config, use all cpus
        else:
            cpuset = ""
            reserve = []

        isolate_cpus, background_cpus, threads = set_cpuset(cpuset, reserve)

        if "clients" in config.keys() and type(config["clients"]) is int:
            clients = abs(config["clients"])
        else:
            clients = 0

        # Use all images if all_images is enabled, otherwise use the provided images (if they exist)
        images = set(config["images"]) if "images" in config.keys() else set()

        if not arguments["all_images"]:
            images = images.intersection(arguments["images"])

        # If the workload is not a Docker workload, use the command from the config
        docker = True
        command = ""
        if "docker" in config.keys() and not config["docker"]:
            if "command" in config.keys() and type(config["command"]) is str:
                docker = False
                command = config["command"]
                images = set(["machine"])
            else:
                continue
        else:
            if len(images) == 0:
                print(f"No correct images provided for workload {workload}")
                continue

        # Create the queue of images for the workload
        queue = init_queue(images, arguments["runs"], arguments["shuffle_mode"])

        # Create the workload
        current_workload = Workload(
            date,
            workload,
            images,
            queue,
            isolate_cpus,
            background_cpus,
            threads,
            arguments["warmup"],
            arguments["pause"],
            arguments["interval"],
            clients,
            arguments["monitor"],
            docker,
            command,
        )

        # Run the workload
        current_workload.prepare()
        current_workload.run()
        # current_workload.remove()
        time.sleep(arguments["pause"])



if __name__ == "__main__":
    main(sys.argv[1:])
