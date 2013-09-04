from abc import ABCMeta
from collections import defaultdict
import os
import time
import sys

import matplotlib.pyplot as plt
import numpy as np
import yaml

from experiment import Experiment

SAVE_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'saved')

class ExperimentSet(object):
    """ Abstract base class used for forming experiment sets.

    Experiment sets are a collection of experiments. They primarily serve two
    purposes:
        1. They vary one independent parameter while holding all other
            parameters fixed.
        2. They run multiple iterations for a given set of parameters and takes
            the average of those results.

    The following class level attributes should be defined by subclasses:
        - name: The name given to the experiment set, e.g., edge_count. This
            name is used for saving files and ideally should not be changed
            because it is used to find file names.
    """
    __metaclass__ = ABCMeta

    def __init__(self, experiment_params, ind_param_name, ind_param_values,
                 prefix, num_experiments):
        required_fields = ['name', 'plot_title', 'plot_xlabel']
        for f in required_fields:
            if not getattr(self, f):
                raise ValueError("self.%s must be defined" % f)

        self.experiment_params = experiment_params
        self.ind_param_name    = ind_param_name
        self.ind_param_values  = ind_param_values
        self.prefix            = prefix
        self.num_experiments   = num_experiments
        for k, v in self.experiment_params.iteritems():
            setattr(self, k, v)
        setattr(self, ind_param_name, ind_param_values)

        if os.path.exists(self._filename()):
            raise ValueError("Experiment Set with this prefix already exists")

        # Save attributes now, for when we want to recreate later.
        self._save(self)

        self.experiments = defaultdict(list)

    ###################################
    # Functions related to computation
    ###################################

    def run_experiments(self, clear=False):
        if clear:
            self.experiments = defaultdict(list)

        experiment_count = sum(len(x) for x in self.experiments.values())
        params = self.experiment_params.copy()

        for val in self.ind_param_values:
            for _ in xrange(self.num_experiments - len(self.experiments[val])):
                experiment_count += 1
                start_time = time.clock()

                params[self.ind_param_name] = val
                exp = Experiment(**params)
                exp.compute_informativeness()
                self.experiments[val].append(exp)

                elapsed_time = time.clock() - start_time
                print "Experiment %d added in %0.2f seconds" % \
                        (experiment_count, elapsed_time)

                self.save_experiment(exp, experiment_count)

        self.aggregate_results()
        self.aggregate_runtimes()

    def aggregate_results(self):
        """ Aggregates results from all the experiments.

        Populates the self.results dict in the following format:
        {
            <correlation type>: {
                <transitive trust model>: {
                    <param_val>: <average informativeness score>,
                    ...
                },
                ...
            },
            ...
        }

        - Value given by edge_count is a point on a line
        - Dict given by transitive trust model defines a line on a graph
        - Dict of dicts given by correlation type gives a set of lines for a graph
        - self.results provides a graph for each type of correlation measure.
        """
        self.results = {}
        for corrname in Experiment.CORRELATION_NAMES:
            self.results[corrname] = {}
            for modelname in Experiment.MODEL_NAMES:
                self.results[corrname][modelname] = {}
                for val in self.ind_param_values:
                    avg_score = np.mean([
                        exp.info_scores[corrname][modelname]
                        for exp in self.experiments[val]])
                    self.results[corrname][modelname][val] = avg_score

        self._save(self.results, "results")

    def aggregate_runtimes(self):
        """ Aggregates te runtime results from all the experiments.

        Populates the self.runtimes dict in the following format:
        {
            <transitive trust model>: {
                <param_val>: <average runtime>,
                ...
            },
            ...
        }
        """
        self.runtimes = {}
        for modelname in Experiment.MODEL_NAMES:
            self.runtimes[modelname] = {}
            for val in self.ind_param_values:
                avg_runtime = np.mean([exp.runtimes[modelname]
                                       for exp in self.experiments[val]])
                self.runtimes[modelname][val] = avg_runtime

    #################################################
    # Functions related to display and visualization
    #################################################

    PLOT_MARKERS = {
        'pagerank': 'b--^',
        'pagerank_weighted': 'b--^',  # Backwards compatibility
        'hitting_pagerank_all': 'g--*',
        'hitting_pagerank_top': 'g--^',
        'hitting_time_all': 'm--*',
        'hitting_time_weighted_all': 'm--*',  # Backwards compatibility
        'hitting_time_top': 'm--^',
        'hitting_time_weighted_top': 'm--^',  # Backwards compatibility
        'max_flow': 'r--s',
        'max_flow_weighted_means': 'r--^',
        'shortest_path': 'c--s',
        'shortest_path_weighted_means': 'c--^'
    }

    def plot(self):
        for corrname in Experiment.CORRELATION_NAMES:
            for modelname in self.results[corrname].keys():
                points = sorted(self.results[corrname][modelname].items())
                plt.plot([x[0] for x in points], [x[1] for x in points],
                         self.PLOT_MARKERS[modelname], label=modelname)
            plt.suptitle(self.plot_title)
            plt.xlabel(self.plot_xlabel)
            plt.ylabel(corrname + ' correlation')
            plt.legend(loc='center left', bbox_to_anchor=(1, 0.5),
                       fancybox=True, shadow=True)
            plt.show()

    def plot_runtimes(self):
        for modelname in Experiment.MODEL_NAMES:
            points = sorted(self.runtimes[modelname].items())
            plt.plot([x[0] for x in points], [x[1] for x in points],
                     self.PLOT_MARKERS[modelname], label=modelname)
        plt.suptitle("Runtimes for transitive trust models")
        plt.xlabel(self.plot_xlabel)
        plt.ylabel("Average Runtime (sec)")
        plt.legend(loc='center left', bbox_to_anchor=(1, 0.5),
                   fancybox=True, shadow=True)
        plt.show()

    def description(self):
        return """\
num_nodes            = {num_nodes}
agent_type_prior     = {agent_type_prior}
edge_strategy        = {edge_strategy}
edges_per_node       = {edges_per_node}
edge_weight_strategy = {edge_weight_strategy}
num_weight_samples   = {num_weight_samples}
prefix               = {prefix}
num_experiments      = {num_experiments}""".format(**self.__dict__)

    ##########################################################
    # Functions related to saving and loading from YAML files
    ##########################################################

    @classmethod
    def load_from_file(cls, prefix, load_experiments=False):
        """ Retrive and load an experiment set from YAML files. """
        base_filename = os.path.join(
            SAVE_FOLDER, "%s_%s.yaml" % (prefix, cls.name))

        if not os.path.exists(base_filename):
            raise ValueError("Save file does not exist.")

        with open(base_filename, 'r') as f:
            exp_set = yaml.load(f.read())

        exp_set.experiments = defaultdict(list)

        if load_experiments:
            exp_set.load_experiments()

        if os.path.exists(exp_set._filename("results")):
            exp_set.results = exp_set._load("results")

        return exp_set

    def save_experiment(self, exp, num):
        """ Saves an experiment to disk. """
        exp_folder = os.path.join(SAVE_FOLDER, "%s_%s" % (self.prefix, self.name))
        if not os.path.exists(exp_folder):
            os.mkdir(exp_folder, 0755)

        exp_filename = os.path.join(exp_folder, "experiment.%03d.yaml" % num)
        if os.path.exists(exp_filename):
            print "Warning: would have overwritten file; backing up."
            new_filename = os.path.join(
                exp_folder, "experiment.%03d.%d.backup.yaml" % (num, time.time()))
            os.rename(exp_filename, new_filename)

        self._save(exp, filename=exp_filename)

    def load_experiments(self):
        """ Loads all experiments for this experiment set into memory. """
        # TODO: Loading experiments is very slow. Consider paring down what gets
        # marshalled and saved? Or consider using a DB.
        print "Warning: This function currently is not optimized and is slow."
        if (hasattr(self, "experiments") and
            isinstance(self.experiments, dict) and
            sum(len(x) for x in self.experiments.values()) != 0):
            raise ValueError("Error: self.experiments is populated. "
                             "Clear before loading to avoid overwriting.")

        exp_folder = os.path.join(SAVE_FOLDER, "%s_%s" % (self.prefix, self.name))
        self.experiments = defaultdict(list)
        num_experiments = 0
        if os.path.exists(exp_folder):
            while True:
                filename = os.path.join(
                    exp_folder, "experiment.%03d.yaml" % (num_experiments + 1))
                if not os.path.exists(filename):
                    break

                exp = self._load(filename=filename)
                self.experiments[exp.graph.edges_per_node].append(exp)
                num_experiments += 1
                sys.stdout.write('.')

        print "%d experiments loaded" % num_experiments

    def _filename(self, suffix=""):
        """ Generates a filename used for saving or loading files. """
        filename = "{prefix}_{name}{suffix}.yaml".format(
            prefix=self.prefix, name=self.name,
            suffix=("_" + suffix if suffix else ""))
        return os.path.join(SAVE_FOLDER, filename)

    def _save(self, obj, suffix="", filename=""):
        """ General purpose function used for saving objects as YAML files. """
        if not filename:
            filename = self._filename(suffix)
        with open(filename, 'w') as f:
            f.write(yaml.dump(obj, indent=2))

    def _load(self, suffix="", filename=""):
        """ General purpose function used for loading objects from YAML. """
        if not filename:
            filename = self._filename(suffix)
        with open(filename, 'r') as f:
            return yaml.load(f.read())

class EdgeCountExperimentSet(ExperimentSet):
    name = 'edge_count'
    plot_xlabel = 'Edges per node'

    DEFAULT_EDGE_COUNTS = [2, 3, 4, 5, 10, 15, 20, 35, 49]  # for num_nodes = 50

    def __init__(self, num_nodes, agent_type_prior, edge_strategy,
                 edge_weight_strategy, num_weight_samples,
                 prefix, num_experiments, edge_counts=None):
        if not edge_counts:
            edge_counts = self.DEFAULT_EDGE_COUNTS

        params = {
            'num_nodes': num_nodes,
            'agent_type_prior': agent_type_prior,
            'edge_strategy': edge_strategy,
            'edge_weight_strategy': edge_weight_strategy,
            'num_weight_samples': num_weight_samples
        }

        self.plot_title = 'Varying edge count with graph of %d nodes' % num_nodes

        super(EdgeCountExperimentSet, self).__init__(
            params, 'edges_per_node', edge_counts, prefix, num_experiments)


class SampleCountExperimentSet(ExperimentSet):
    name = 'sample_count'
    plot_xlabel = 'Number of samples per edge'

    # TODO: Need to figure out how to plot infinity
    # DEFAULT_SAMPLE_COUNTS = [1, 2, 3, 4, 5, 10, 20, 100, float('inf')]
    DEFAULT_SAMPLE_COUNTS = [1, 2, 3, 4, 5, 10, 20, 100]

    def __init__(self, num_nodes, agent_type_prior, edge_strategy,
                 edges_per_node, edge_weight_strategy, prefix,
                 num_experiments, sample_counts=None):
        if not sample_counts:
            sample_counts = self.DEFAULT_SAMPLE_COUNTS

        params = {
            'num_nodes': num_nodes,
            'agent_type_prior': agent_type_prior,
            'edge_strategy': edge_strategy,
            'edges_per_node': edges_per_node,
            'edge_weight_strategy': edge_weight_strategy,
        }

        self.plot_title = 'Varying edge samples with graph of %d nodes' % num_nodes

        super(SampleCountExperimentSet, self).__init__(
            params, 'num_weight_samples', sample_counts, prefix, num_experiments)
