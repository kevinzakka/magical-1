import abc
import enum

from gym.utils import EzPickle
import numpy as np

from milbench.base_env import BaseEnv, ez_init
import milbench.entities as en
import milbench.geom as geom

# As with match_regions.py, we keep colours array internal because some of the
# hard-coded constants depend on the number of colours not expanding. We need
# to keep shape types internal for the same reason.
# TODO: factor these out; they're actually common to all tasks now.
ALL_COLOURS = np.array([
    en.ShapeColour.RED,
    en.ShapeColour.GREEN,
    en.ShapeColour.BLUE,
    en.ShapeColour.YELLOW,
],
                       dtype='object')
ALL_SHAPE_TYPES = np.array([
    en.ShapeType.STAR,
    en.ShapeType.SQUARE,
    en.ShapeType.PENTAGON,
    en.ShapeType.CIRCLE,
],
                           dtype='object')


class BaseClusterEnv(BaseEnv, abc.ABC):
    """There are blocks of many colours and types. You must arrange them into
    distinct clusters. Depending on the demo, cluster membership must either be
    determined by shape type or shape colour (but if it's determined by one
    characteristic in the demo then it should be independent of the other
    characteristic). There should be exactly one cluster for each value of the
    membership characteristic (e.g. if clustering on colour, there should be
    one blue cluster, one red cluster, etc.).

    This class should not be instantiated directly. Instead, you should use
    ClusterColourEnv or ClusterShapeEnv."""
    class ClusterBy(str, enum.Enum):
        """What characteristic should blocks be clustered by?"""
        COLOUR = 'colour'
        TYPE = 'type'
        # TODO: add a 'both' option! (will require another demo scenario)

    def __init__(
            self,
            # should we randomise assignment of colours to blocks, or use
            # default ordering?
            rand_shape_colour=False,
            # should we randomise assignment of types to blocks, or use default
            # ordering?
            rand_shape_type=False,
            # should we jitter the positions of blocks and the robot?
            rand_layout_minor=False,
            # should we fully randomise the positions of blocks and the robot?
            rand_layout_full=False,
            # should we randomise number of blocks? (this requires us to
            # randomise everything else, too)
            rand_shape_count=False,
            # which block characteristic do we want the user to pay attention
            # to for clustering? (colour vs. shape type)
            cluster_by=ClusterBy.COLOUR,
            **kwargs):
        super().__init__(**kwargs)
        self.rand_shape_colour = rand_shape_colour
        self.rand_shape_type = rand_shape_type
        self.rand_shape_count = rand_shape_count
        assert not (rand_layout_minor and rand_layout_full)
        self.rand_layout_minor = rand_layout_minor
        self.rand_layout_full = rand_layout_full
        self.cluster_by = cluster_by
        if self.rand_shape_count:
            assert self.rand_layout_full, \
                "if shape count is randomised then layout must also be " \
                "fully randomised"
            assert self.rand_shape_type, \
                "if shape count is randomised then shape type must also be " \
                "randomised"
            assert self.rand_shape_colour, \
                "if shape count is randomised then colour must be " \
                "randomised too"

    @classmethod
    def make_name(cls, suffix=None):
        pass

    def on_reset(self):
        # make the robot at default position (will be randomised at end if
        # rand_layout is true)
        robot = self._make_robot(*self.DEFAULT_ROBOT_POSE)

        # 3x blue & 2x of each other colour
        default_colours = self.DEFAULT_BLOCK_COLOURS
        # 3x pentagon & 2x of each other shape type
        default_shape_types = self.DEFAULT_BLOCK_SHAPES
        # these were generated by randomly scattering shapes about the chosen
        # default robot position and then rounding down values a bit
        default_poses = self.DEFAULT_BLOCK_POSES
        default_n_shapes = len(default_colours)

        if self.rand_shape_count:
            n_shapes = self.rng.randint(7, 10 + 1)
            # rand_shape_count=True implies rand_layout=True, so these MUST be
            # randomised at the end
            poses = [((0, 0), 0)] * n_shapes
        else:
            n_shapes = default_n_shapes
            # if rand_layout=True, these will be randomised at the end
            poses = default_poses

        if self.rand_shape_colour:
            # make sure we have at least one of each colour
            colours = list(ALL_COLOURS)
            colours.extend([
                self.rng.choice(ALL_COLOURS)
                for _ in range(n_shapes - len(colours))
            ])
            self.rng.shuffle(colours)
        else:
            colours = default_colours

        if self.rand_shape_type:
            # make sure we have at least one of each type, too
            shape_types = list(ALL_SHAPE_TYPES)
            shape_types.extend([
                self.rng.choice(ALL_SHAPE_TYPES)
                for _ in range(n_shapes - len(shape_types))
            ])
            self.rng.shuffle(shape_types)
        else:
            shape_types = default_shape_types

        assert len(poses) == n_shapes
        assert len(colours) == n_shapes
        assert len(shape_types) == n_shapes

        shape_ents = []
        for ((x, y), angle), colour, shape_type \
                in zip(poses, colours, shape_types):
            shape = self._make_shape(shape_type=shape_type,
                                     colour_name=colour,
                                     init_pos=(x, y),
                                     init_angle=angle)
            shape_ents.append(shape)
        self.add_entities(shape_ents)

        # make index mapping characteristic values to blocks
        if self.cluster_by == self.ClusterBy.COLOUR:
            c_values_list = np.asarray(colours, dtype='object')
            self.__characteristic_values = np.unique(c_values_list)
        elif self.cluster_by == self.ClusterBy.TYPE:
            c_values_list = np.asarray(shape_types, dtype='object')
            self.__characteristic_values = np.unique(c_values_list)
        else:
            raise NotImplementedError(
                f"don't know how to cluster by '{self.cluster_by}'")
        self.__blocks_by_characteristic = {}
        assert len(c_values_list) == len(shape_ents)
        for shape, c_value in zip(shape_ents, c_values_list):
            c_list = self.__blocks_by_characteristic.setdefault(c_value, [])
            c_list.append(shape)

        # as in match_regions.py, this should be added after all shapes so it
        # appears on top, but before layout randomisation so that it gets added
        # to the space correctly
        self.add_entities([robot])

        if self.rand_layout_full or self.rand_layout_minor:
            if self.rand_layout_full:
                pos_limit = rot_limit = None
            else:
                pos_limit = self.JITTER_POS_BOUND
                rot_limit = self.JITTER_ROT_BOUND
            geom.pm_randomise_all_poses(space=self._space,
                                        entities=[robot, *shape_ents],
                                        arena_lrbt=self.ARENA_BOUNDS_LRBT,
                                        rng=self.rng,
                                        rand_pos=True,
                                        rand_rot=True,
                                        rel_pos_linf_limits=pos_limit,
                                        rel_rot_limits=rot_limit)

        # set up index for lookups
        self.__ent_index = en.EntityIndex(shape_ents)

        print('init score', self.score_on_end_of_traj())

    def score_on_end_of_traj(self):
        # Compute centroids for each value of the relevant characteristic
        # (either colour or shape type). Also compute mean squared distance
        # from centroid for each block in the cluster.
        nvals = len(self.__characteristic_values)
        centroids = np.zeros((nvals, 2))
        for c_idx, c_value in enumerate(self.__characteristic_values):
            c_blocks = self.__blocks_by_characteristic.get(c_value)
            if not c_blocks:
                centroid = (0, 0)
            else:
                positions = np.asarray([(b.shape_body.position.x,
                                         b.shape_body.position.y)
                                        for b in c_blocks])
                centroid = np.mean(positions, axis=0)
            centroids[c_idx] = centroid

        # Now for each block compute whether squared distance to nearest
        # incorrect centroid. A block is correctly clustered if the true
        # centroid is closer than the next-nearest centroid by a margin of at
        # least min_margin * (mean variation within true centroid). This
        # rewards tight clusterings.
        min_margin = 2.0  # higher = more strict
        n_blocks = 0
        n_correct = 0
        for c_idx, c_value in enumerate(self.__characteristic_values):
            for block in self.__blocks_by_characteristic.get(c_value, []):
                n_blocks += 1
                block_pos = np.array([[
                    block.shape_body.position.x,
                    block.shape_body.position.y,
                ]])
                centroid_sses = np.sum((block_pos - centroids)**2, axis=1)
                indices = np.arange(len(self.__characteristic_values))
                true_sse, = centroid_sses[indices == c_idx]
                bad_sses = centroid_sses[indices != c_idx]
                nearest_bad_centroid = np.min(bad_sses)
                true_centroid_sse = centroid_sses[c_idx]
                margin = min_margin * true_centroid_sse
                n_correct += int(
                    np.sqrt(true_sse) < np.sqrt(nearest_bad_centroid) - margin)

        # rescale so that frac_correct <= thresh gives 0 score, frac_correct ==
        # 1.0 gives 1 score. I've found it's common to frac_correct ranging
        # from 0.2 up to 0.4 just from random init; this clipping process means
        # that random init gives close to 0 average score.
        frac_correct = float(n_correct) / max(n_blocks, 1)
        thresh = 0.75
        score = max(frac_correct - thresh, 0) / (1 - thresh)

        return score


class ClusterColourEnv(BaseClusterEnv, EzPickle):
    DEFAULT_ROBOT_POSE = ((0.71692, -0.34374), 0.83693)
    DEFAULT_BLOCK_COLOURS = [
        en.ShapeColour.BLUE,
        en.ShapeColour.BLUE,
        en.ShapeColour.BLUE,
        en.ShapeColour.GREEN,
        en.ShapeColour.GREEN,
        en.ShapeColour.RED,
        en.ShapeColour.YELLOW,
        en.ShapeColour.YELLOW,
    ]
    DEFAULT_BLOCK_SHAPES = [
        en.ShapeType.CIRCLE,
        en.ShapeType.STAR,
        en.ShapeType.SQUARE,
        en.ShapeType.PENTAGON,
        en.ShapeType.PENTAGON,
        en.ShapeType.SQUARE,
        en.ShapeType.STAR,
        en.ShapeType.PENTAGON,
    ]
    DEFAULT_BLOCK_POSES = [
        ((-0.5147, 0.14149), -0.38871),
        ((-0.1347, -0.71414), 1.0533),
        ((-0.74247, -0.097592), 1.1571),
        ((-0.077363, -0.42964), -0.64379),
        ((0.51978, 0.1853), -1.1762),
        ((-0.5278, -0.21642), 2.9356),
        ((-0.54039, 0.48292), 0.072818),
        ((-0.16761, 0.64303), -2.3255),
    ]

    @ez_init()
    def __init__(self, *args, **kwargs):
        super().__init__(*args,
                         cluster_by=BaseClusterEnv.ClusterBy.COLOUR,
                         **kwargs)

    @classmethod
    def make_name(cls, suffix=None):
        base_name = 'ClusterColour'
        return base_name + (suffix or '') + '-v0'


class ClusterShapeEnv(BaseClusterEnv, EzPickle):
    # demo variant
    DEFAULT_ROBOT_POSE = ((0.286, -0.202), -1.878)
    DEFAULT_BLOCK_COLOURS = [
        en.ShapeColour.YELLOW,
        en.ShapeColour.BLUE,
        en.ShapeColour.RED,
        en.ShapeColour.RED,
        en.ShapeColour.GREEN,
        en.ShapeColour.YELLOW,
        en.ShapeColour.BLUE,
        en.ShapeColour.GREEN,
    ]
    DEFAULT_BLOCK_SHAPES = [
        en.ShapeType.SQUARE,
        en.ShapeType.PENTAGON,
        en.ShapeType.PENTAGON,
        en.ShapeType.PENTAGON,
        en.ShapeType.CIRCLE,
        en.ShapeType.STAR,
        en.ShapeType.STAR,
        en.ShapeType.CIRCLE,
    ]
    DEFAULT_BLOCK_POSES = [
        ((-0.414, 0.297), -1.731),
        ((0.068, 0.705), 2.184),
        ((0.821, 0.220), 0.650),
        ((-0.461, -0.749), -2.673),
        ((0.867, -0.149), -2.215),
        ((-0.785, -0.140), -0.405),
        ((-0.305, -0.226), 1.341),
        ((0.758, -0.708), -2.140),
    ]

    @ez_init()
    def __init__(self, *args, **kwargs):
        super().__init__(*args,
                         cluster_by=BaseClusterEnv.ClusterBy.TYPE,
                         **kwargs)

    @classmethod
    def make_name(cls, suffix=None):
        base_name = 'ClusterShape'
        return base_name + (suffix or '') + '-v0'
