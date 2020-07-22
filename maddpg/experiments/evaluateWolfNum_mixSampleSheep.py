import os
import sys
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['KMP_DUPLICATE_LIB_OK']='True'
dirName = os.path.dirname(__file__)
sys.path.append(os.path.join(dirName, '..'))
sys.path.append(os.path.join(dirName, '..', '..'))
import logging
logging.getLogger('tensorflow').setLevel(logging.ERROR)

from environment.chasingEnv.multiAgentEnv import *
from functionTools.loadSaveModel import saveToPickle, restoreVariables, loadFromPickle
from functionTools.trajectory import SampleTrajectory
from environment.chasingEnv.multiAgentEnvWithIndividReward import RewardWolfIndividual

from maddpg.maddpgAlgor.trainer.myMADDPG import *
import pandas as pd
import matplotlib.pyplot as plt
from collections import OrderedDict
import random

wolfColor = np.array([0.85, 0.35, 0.35])
sheepColor = np.array([0.35, 0.85, 0.35])
blockColor = np.array([0.25, 0.25, 0.25])

def calcTrajRewardWithSharedWolfReward(traj):
    rewardIDinTraj = 2
    rewardList = [timeStepInfo[rewardIDinTraj][0] for timeStepInfo in traj]
    trajReward = np.sum(rewardList)
    return trajReward

def calcTrajRewardWithIndividualWolfReward(traj, wolvesID):
    rewardIDinTraj = 2
    getWolfReward = lambda allAgentsReward: np.sum([allAgentsReward[wolfID] for wolfID in wolvesID])
    rewardList = [getWolfReward(timeStepInfo[rewardIDinTraj]) for timeStepInfo in traj]
    trajReward = np.sum(rewardList)
    return trajReward

class EvaluateWolfSheepTrain:
    def __init__(self, getSheepModelPaths):
        self.getSheepModelPaths = getSheepModelPaths
        self.getSampledSheepPath = lambda sheepPaths: sheepPaths[random.randint(0, len(sheepPaths) - 1)]

    # def getSampledSheepPath(self, sheepPaths):
    #     sampleID = random.randint(0, len(sheepPaths) - 1)
    #     print(sampleID)
    #     return sheepPaths[sampleID]

    def __call__(self, df):
        numWolves = df.index.get_level_values('numWolves')[0]
        sheepSpeedMultiplier = df.index.get_level_values('sheepSpeedMultiplier')[0]# [1, 1.25]
        wolfIndividual = df.index.get_level_values('wolfIndividual')[0] #[shared, individ]

        numSheeps = 1
        numBlocks = 2
        maxTimeStep = 75
        maxEpisode = 60000

        numAgents = numWolves + numSheeps
        numEntities = numAgents + numBlocks
        wolvesID = list(range(numWolves))
        sheepsID = list(range(numWolves, numAgents))
        blocksID = list(range(numAgents, numEntities))

        wolfSize = 0.075
        sheepSize = 0.05
        blockSize = 0.2
        entitiesSizeList = [wolfSize] * numWolves + [sheepSize] * numSheeps + [blockSize] * numBlocks

        wolfMaxSpeed = 1.0
        blockMaxSpeed = None
        sheepMaxSpeedOriginal = 1.3
        sheepMaxSpeed = sheepMaxSpeedOriginal * sheepSpeedMultiplier
        entityMaxSpeedList = [wolfMaxSpeed] * numWolves + [sheepMaxSpeed] * numSheeps + [blockMaxSpeed] * numBlocks

        entitiesMovableList = [True] * numAgents + [False] * numBlocks
        massList = [1.0] * numEntities

        isCollision = IsCollision(getPosFromAgentState)
        punishForOutOfBound = PunishForOutOfBound()
        rewardSheep = RewardSheep(wolvesID, sheepsID, entitiesSizeList, getPosFromAgentState, isCollision, punishForOutOfBound)

        rewardWolfIndivid = RewardWolfIndividual(wolvesID, sheepsID, entitiesSizeList, isCollision)
        rewardWolfShared = RewardWolf(wolvesID, sheepsID, entitiesSizeList, isCollision)

        rewardFuncIndividWolf = lambda state, action, nextState: \
            list(rewardWolfIndivid(state, action, nextState)) + list(rewardSheep(state, action, nextState))
        rewardFuncSharedWolf = lambda state, action, nextState: \
            list(rewardWolfShared(state, action, nextState)) + list(rewardSheep(state, action, nextState))

        reset = ResetMultiAgentChasing(numAgents, numBlocks)
        observeOneAgent = lambda agentID: Observe(agentID, wolvesID, sheepsID, blocksID, getPosFromAgentState, getVelFromAgentState)
        observe = lambda state: [observeOneAgent(agentID)(state) for agentID in range(numAgents)]

        reshapeAction = ReshapeAction()
        getCollisionForce = GetCollisionForce()
        applyActionForce = ApplyActionForce(wolvesID, sheepsID, entitiesMovableList)
        applyEnvironForce = ApplyEnvironForce(numEntities, entitiesMovableList, entitiesSizeList,
                                              getCollisionForce, getPosFromAgentState)
        integrateState = IntegrateState(numEntities, entitiesMovableList, massList,
                                        entityMaxSpeedList, getVelFromAgentState, getPosFromAgentState)
        transit = TransitMultiAgentChasing(numEntities, reshapeAction, applyActionForce, applyEnvironForce, integrateState)

        isTerminal = lambda state: False
        maxRunningStepsToSample = 75
        sampleTrajectoryIndivid = SampleTrajectory(maxRunningStepsToSample, transit, isTerminal, rewardFuncIndividWolf, reset)
        sampleTrajectoryShared = SampleTrajectory(maxRunningStepsToSample, transit, isTerminal, rewardFuncSharedWolf, reset)
        sampleTrajectory = sampleTrajectoryIndivid if wolfIndividual == 'individ' else sampleTrajectoryShared

        initObsForParams = observe(reset())
        obsShape = [initObsForParams[obsID].shape[0] for obsID in range(len(initObsForParams))]
        worldDim = 2
        actionDim = worldDim * 2 + 1
        buildMADDPGModels = BuildMADDPGModels(actionDim, numAgents, obsShape)
        layerWidth = [128, 128]
        modelsList = [buildMADDPGModels(layerWidth, agentID) for agentID in range(numAgents)]

        sheepModel = modelsList[sheepsID[0]]
        wolvesModels = modelsList[:-1]

        dirName = os.path.dirname(__file__)
        fileName = "maddpg{}wolves{}sheep{}blocks{}episodes{}stepSheepSpeed{}{}_agent".format(
            numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep, sheepSpeedMultiplier, wolfIndividual)
        folderName = 'evalOneSheep_2575steps_1to6wolves_11.25speed'
        wolfModelPaths = [os.path.join(dirName, '..', 'trainedModels', folderName, fileName + str(i)) for i in wolvesID]
        [restoreVariables(model, path) for model, path in zip(wolvesModels, wolfModelPaths)]

        sheepPaths = self.getSheepModelPaths(numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep)

        rewardList = []
        trajList = []
        numTrajToSample = 5000
        for i in range(numTrajToSample):
            # sheep
            sheepPath = self.getSampledSheepPath(sheepPaths)
            # print(sheepPath)
            restoreVariables(sheepModel, sheepPath)

            actOneStepOneModel = ActOneStep(actByPolicyTrainNoisy)
            policy = lambda allAgentsStates: [actOneStepOneModel(model, observe(allAgentsStates)) for model in modelsList]

            traj = sampleTrajectory(policy)
            rew = calcTrajRewardWithSharedWolfReward(traj) if wolfIndividual == 'shared' else calcTrajRewardWithIndividualWolfReward(traj, wolvesID)
            rewardList.append(rew)
            trajList.append(list(traj))

        trajectoryDirectory = os.path.join(dirName, '..', 'trajectories', folderName)
        if not os.path.exists(trajectoryDirectory):
            os.makedirs(trajectoryDirectory)
        trajFileName = "maddpg{}wolves{}sheep{}blocks{}episodes{}stepSheepSpeed{}{}_mixTraj".format(
            numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep, sheepSpeedMultiplier, wolfIndividual)
        trajSavePath = os.path.join(trajectoryDirectory, trajFileName)
        saveToPickle(trajList, trajSavePath)

        meanTrajReward = np.mean(rewardList)
        seTrajReward = np.std(rewardList) / np.sqrt(len(rewardList) - 1)
        print('meanTrajRewardSharedWolf', meanTrajReward, 'se ', seTrajReward)

        return pd.Series({'mean': meanTrajReward, 'se': seTrajReward})


class GetSheepModelPaths:
    def __init__(self, sheepSpeedList, wolfTypeList):
        self.sheepSpeedList = sheepSpeedList
        self.wolfTypeList = wolfTypeList

    def __call__(self, numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep):
        dirName = os.path.dirname(__file__)
        folderName = 'evalOneSheep_2575steps_1to6wolves_11.25speed'
        fileNameList = ["maddpg{}wolves{}sheep{}blocks{}episodes{}stepSheepSpeed{}{}_agent{}".format(
            numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep, sheepSpeedMultiplier, wolfIndividual, numWolves)
            for sheepSpeedMultiplier in self.sheepSpeedList for wolfIndividual in self.wolfTypeList]
        sheepPaths = [os.path.join(dirName, '..', 'trainedModels', folderName, fileName) for fileName in fileNameList]

        return sheepPaths


def main():
    independentVariables = OrderedDict()
    independentVariables['wolfIndividual'] = ['shared', 'individ']
    independentVariables['numWolves'] = [1, 2, 3, 4, 5, 6]
    independentVariables['sheepSpeedMultiplier'] = [1.0, 1.25]

    getSheepModelPaths = GetSheepModelPaths(independentVariables['sheepSpeedMultiplier'], independentVariables['wolfIndividual'])
    evaluateWolfSheepTrain = EvaluateWolfSheepTrain(getSheepModelPaths)

    levelNames = list(independentVariables.keys())
    levelValues = list(independentVariables.values())
    levelIndex = pd.MultiIndex.from_product(levelValues, names=levelNames)
    toSplitFrame = pd.DataFrame(index=levelIndex)
    # resultDF = toSplitFrame.groupby(levelNames).apply(evaluateWolfSheepTrain)

    resultPath = os.path.join(dirName, '..', 'evalResults')
    resultLoc = os.path.join(resultPath, 'evalWolfNumberWithOneSheep_75steps_sample75_mixSampleSheep.pkl')

    # saveToPickle(resultDF, resultLoc)

    resultDF = loadFromPickle(resultLoc)
    print(resultDF)
    figure = plt.figure(figsize=(10, 5))
    plotCounter = 1
    numRows = 1
    numColumns = len(independentVariables['sheepSpeedMultiplier'])
    for keyCol, outterSubDf in resultDF.groupby('sheepSpeedMultiplier'):
        outterSubDf.index = outterSubDf.index.droplevel('sheepSpeedMultiplier')
        axForDraw = figure.add_subplot(numRows, numColumns, plotCounter)
        for keyRow, innerSubDf in outterSubDf.groupby('wolfIndividual'):
            innerSubDf.index = innerSubDf.index.droplevel('wolfIndividual')
            plt.ylim([0, 500])
            innerSubDf.plot.line(ax = axForDraw, y='mean', yerr='se', label = keyRow, uplims=True, lolims=True, capsize=3)

        axForDraw.title.set_text('sheep speed: ' + str(keyCol) + 'x')
        if plotCounter == 1:
            axForDraw.set_ylabel('Mean Eps Reward')
        axForDraw.set_xlabel('Number of Wolves')
        plotCounter += 1
        axForDraw.set_aspect(0.01, adjustable='box')

        plt.legend(title='Wolf type')

    plt.suptitle('1~6 wolves vs 1 sheep, train 75 steps, sampling 75 steps/eps, mix sample sheep')


    plt.savefig(os.path.join(resultPath, 'evalWolfNumberWithOneSheep_75steps_sample75_mixSampleSheep'))
    plt.show()


if __name__ == '__main__':
    main()
